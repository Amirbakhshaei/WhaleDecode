import type { WorkerEvent } from "../types.js";
import type { CounterpartyClass, StealthResult } from "./counterparty.js";

export interface EventIntel {
  lar: number | null;
  counterparty: CounterpartyClass;
  narrative: string;
  stealth: StealthResult;
}

const esc = (s: string): string => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const fmtUsd = (n: number): string =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(2)}M` : n >= 1_000 ? `$${(n / 1_000).toFixed(1)}K` : `$${n.toFixed(0)}`;

export function renderCardSvg(ev: WorkerEvent, intel: EventIntel): string {
  const entity = esc(ev.wallet?.label || "Unknown Whale");
  const impact = intel.lar === null ? "n/a" : `${intel.lar}%`;
  const impactColor = intel.lar !== null && intel.lar >= 5 ? "#ff4d6d" : intel.lar !== null && intel.lar >= 1 ? "#ffd166" : "#4dd4ac";
  const stealthBadge = intel.stealth.flagged
    ? `<rect x="880" y="540" width="280" height="60" rx="12" fill="#1b2a4a"/><text x="1020" y="578" font-family="monospace" font-size="26" fill="#8ab4ff" text-anchor="middle">STEALTH x${intel.stealth.siblings + 1}</text>`
    : "";
  const conviction = esc(intel.counterparty.conviction.toUpperCase());

  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#0b0e17"/>
  <rect x="24" y="24" width="1152" height="627" rx="24" fill="#111624" stroke="#2a3350" stroke-width="2"/>
  <text x="64" y="96" font-family="monospace" font-size="28" fill="#7f8ab3">WHALEDECODE DEEP INTELLIGENCE</text>
  <text x="64" y="120" font-family="sans-serif" font-size="34" font-weight="bold" fill="#e8ecff">${esc(ev.chain.toUpperCase())} · ${esc(ev.assetSymbol)} · ${esc(ev.actionType.toUpperCase())}</text>
  <text x="64" y="220" font-family="sans-serif" font-size="52" font-weight="bold" fill="#ffffff">${entity}</text>
  <text x="64" y="270" font-family="monospace" font-size="30" fill="#9aa5c9">${esc(intel.counterparty.detail)}</text>
  <text x="64" y="360" font-family="monospace" font-size="52" fill="#4dd4ac">${fmtUsd(Number(ev.usdValue))}</text>
  <text x="64" y="410" font-family="monospace" font-size="30" fill="#9aa5c3">${esc(String(ev.amount))} ${esc(ev.assetSymbol)} @ $${esc(Number(ev.enrichment?.priceUsd ?? 0).toFixed(4))}</text>
  <text x="64" y="500" font-family="monospace" font-size="28" fill="#9aa5c3">Liquidity Absorption</text>
  <text x="64" y="545" font-family="monospace" font-size="40" fill="${impactColor}">${esc(impact)}</text>
  <rect x="64" y="560" width="500" height="14" rx="7" fill="#1b2236"/>
  <rect x="64" y="560" width="${Math.min(500, Math.round(((intel.lar ?? 0) / 10) * 500))}" height="14" rx="7" fill="${impactColor}"/>
  <rect x="640" y="470" width="300" height="60" rx="12" fill="#1b2a4a"/>
  <text x="790" y="508" font-family="monospace" font-size="24" fill="#8ab4ff" text-anchor="middle">${esc(intel.narrative)}</text>
  <rect x="640" y="540" width="220" height="60" rx="12" fill="#1b2a4a"/>
  <text x="750" y="578" font-family="monospace" font-size="26" fill="#c3a6ff" text-anchor="middle">${conviction}</text>
  ${stealthBadge}
  <text x="1136" y="628" font-family="monospace" font-size="20" fill="#4a5470" text-anchor="end">@WhaleDecodeBot</text>
</svg>`;
}

export function generateCard(ev: WorkerEvent, intel: EventIntel): Buffer {
  return Buffer.from(renderCardSvg(ev, intel), "utf8");
}

import assert from "node:assert/strict";
import { test } from "node:test";
import { renderCardSvg, generateCard } from "../src/services/cardGenerator.js";
import type { WorkerEvent } from "../src/types.js";
import type { EventIntel } from "../src/services/cardGenerator.js";

const intel: EventIntel = {
  lar: 4.8,
  counterparty: { kind: "cold", detail: "Cold storage / custody destination", conviction: "high" },
  narrative: "Macro Settlement",
  stealth: { flagged: true, siblings: 2, windowHours: 6, maxUsd: 50_000 },
};

const ev: WorkerEvent = {
  idempotencyKey: "k", chain: "ethereum", txHash: "0xtx", logIndex: 0,
  fromAddress: "0xfrom", toAddress: "0xto", assetSymbol: "ETH", amount: "450.2",
  usdValue: 1_420_000, actionType: "swap",
  wallet: { address: "0xw", label: 'Arthur <Hayes> "Maelstrom"', category: "Venture Treasury", chain: "ethereum" },
  enrichment: { priceUsd: 3154 },
};

test("SVG card is 1200x675 and escapes entity names", () => {
  const svg = renderCardSvg(ev, intel);
  assert.ok(svg.includes('width="1200"'));
  assert.ok(svg.includes('height="675"'));
  assert.ok(!svg.includes("Arthur <Hayes>"));
  assert.ok(svg.includes("&lt;Hayes&gt;"));
  assert.ok(svg.includes("STEALTH x3"));
  assert.ok(svg.includes("4.8%"));
});

test("generateCard returns a Buffer of an honest SVG document", () => {
  const buf = generateCard(ev, intel);
  assert.ok(Buffer.isBuffer(buf));
  const text = buf.toString("utf8");
  assert.ok(text.startsWith("<svg"));
  assert.ok(text.trimEnd().endsWith("</svg>"));
});

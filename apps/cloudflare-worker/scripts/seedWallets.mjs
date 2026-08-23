#!/usr/bin/env node
// Emit INSERT statements for curated_wallets from the repo's wallets_verified.json.
// Pipe the output into D1:
//   node scripts/seedWallets.mjs | wrangler d1 execute whaledecode --local --file=-

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const file = process.argv[2] || resolve(root, "wallets_verified.json");

const CHAIN_MAP = {
  ETH: "ethereum",
  ETHEREUM: "ethereum",
  ARB: "arbitrum",
  ARBITRUM: "arbitrum",
  BASE: "base",
  BSC: "bsc",
  BNB: "bsc",
  POLYGON: "polygon",
  MATIC: "polygon",
};

function sqlStr(s) {
  return `'${String(s).replace(/'/g, "''")}'`;
}

const wallets = JSON.parse(readFileSync(file, "utf8"));
let n = 0;
for (const w of wallets) {
  const chain = CHAIN_MAP[String(w.chain || "").toUpperCase()] || String(w.chain).toLowerCase();
  const address = String(w.address).toLowerCase();
  const label = w.label || "";
  const tags = JSON.stringify(w.tags || []);
  console.log(
    `INSERT OR IGNORE INTO curated_wallets (address, chain, label, tags, is_active) VALUES (${sqlStr(address)}, ${sqlStr(chain)}, ${sqlStr(label)}, ${sqlStr(tags)}, 1);`,
  );
  n++;
}
console.error(`# wrote ${n} curated wallet inserts`);

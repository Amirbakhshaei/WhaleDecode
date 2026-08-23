#!/usr/bin/env node
// One-time setup: register Alchemy Notify (Address Activity) webhooks that
// point at the deployed Worker. Run AFTER `wrangler deploy` so WORKER_URL exists.
//
//   ALCHEMY_AUTH_TOKEN=... ALCHEMY_SIGNING_KEY=... WORKER_URL=https://<your>.workers.dev/webhook/alchemy \
//     node scripts/registerWebhooks.mjs wallets.json
//
// wallets.json: [{ "address": "0x...", "chain": "ethereum" }, ...]
// The script prints each created webhook ID — save them as
// ALCHEMY_WEBHOOK_ID_ETH / _ARB / _BASE in your deploy secrets.

import { readFileSync } from "node:fs";

const AUTH = process.env.ALCHEMY_AUTH_TOKEN;
const SIGNING = process.env.ALCHEMY_SIGNING_KEY;
const WORKER_URL = process.env.WORKER_URL;
const WALLETS_FILE = process.argv[2] || "wallets.json";

if (!AUTH || !SIGNING || !WORKER_URL) {
  console.error(
    "Missing env: ALCHEMY_AUTH_TOKEN, ALCHEMY_SIGNING_KEY, WORKER_URL",
  );
  process.exit(1);
}

const wallets = JSON.parse(readFileSync(WALLETS_FILE, "utf8"));
const byChain = {};
for (const w of wallets) {
  (byChain[w.chain.toLowerCase()] ||= []).push(w.address);
}

const NETWORKS = {
  ethereum: "ETH_MAINNET",
  arbitrum: "ARB_MAINNET",
  base: "BASE_MAINNET",
};

for (const [chain, addresses] of Object.entries(byChain)) {
  const network = NETWORKS[chain] || `${chain.toUpperCase()}_MAINNET`;
  const body = {
    network,
    webhook_type: "ADDRESS_ACTIVITY",
    webhook_url: WORKER_URL,
    signing_key: SIGNING,
    addresses,
  };
  const res = await fetch("https://dashboard.alchemy.com/api/create-webhook", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Alchemy-Token": AUTH,
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  console.log(`${chain}: HTTP ${res.status}`, JSON.stringify(data));
  if (data.id) {
    console.log(`  -> set ALCHEMY_WEBHOOK_ID_${chain.toUpperCase()}=${data.id}`);
  }
}

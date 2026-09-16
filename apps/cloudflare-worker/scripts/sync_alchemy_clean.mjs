#!/usr/bin/env node
/**
 * sync_alchemy_clean.mjs — automated Alchemy webhook address sync
 * ponytail: uses wrangler CLI + native fetch; no extra dependencies
 */
import { execSync } from "child_process";
import fs from "fs";
import path from "path";

const DB_NAME = "whaledecode_db";
const SAVE_PATH = path.resolve(import.meta.dirname, ".last_alchemy_clean.json");
const ALCHEMY_URL = process.env.ALCHEMY_WEBHOOK_URL || "https://dashboard.alchemy.com/api/update-webhook-addresses";

// ponytail: parse .env manually so script works without dotenv dependency
function loadEnvFile(p) {
  try {
    const txt = fs.readFileSync(p, "utf-8");
    for (const line of txt.split(/\r?\n/)) {
      const idx = line.indexOf("=");
      if (idx > 0 && !line.startsWith("#")) {
        const k = line.slice(0, idx).trim();
        const v = line.slice(idx + 1).trim();
        if (k && process.env[k] === undefined) process.env[k] = v.replace(/^["']|["']$/g, "");
      }
    }
  } catch {}
}
loadEnvFile(path.resolve(import.meta.dirname, "../.env"));

const WEBHOOK_ID = process.env.ALCHEMY_WEBHOOK_ID || process.env.ALCHEMY_WEBHOOK_ID_ETH || "";
const API_TOKEN = process.env.ALCHEMY_API_KEY || process.env.ALCHEMY_AUTH_TOKEN || "";
const USE_REMOTE = !!process.env.USE_REMOTE;

function runD1(query) {
  const localFlag = USE_REMOTE ? "" : "--local";
  const cmd = `npx wrangler d1 execute ${DB_NAME} ${localFlag} --json --command "${query}"`;
  const out = execSync(cmd, {
    cwd: path.resolve(import.meta.dirname, ".."),
    encoding: "utf-8",
    maxBuffer: 10 * 1024 * 1024,
    stdio: ["pipe", "pipe", "pipe"],
  });
  // wrangler sometimes logs before JSON; find the JSON array/object start
  const idx = out.indexOf("[");
  const jsonPart = idx >= 0 ? out.substring(idx) : out;
  const parsed = JSON.parse(jsonPart);
  // wrangler --json returns array of result objects sometimes
  const inner = Array.isArray(parsed) ? parsed[0] : parsed;
  return inner?.results || inner || [];
}

async function main() {
  console.log("[sync] Querying D1 for clean whale wallets ...");

  const rows = runD1("SELECT address, label, quality_score FROM curated_wallets WHERE is_active = 1 AND is_exchange = 0 AND is_mev = 0 ORDER BY quality_score DESC LIMIT 50");
  const current = (Array.isArray(rows) ? rows : (rows?.results || [])).map((r) => {
    const addr = (r.address || r.address || r?.address || "").toLowerCase();
    return addr;
  }).filter(Boolean);

  const uniqueCurrent = [...new Set(current)];
  console.log(`[sync] Selected ${uniqueCurrent.length} clean wallets (top 50 by quality_score)`);

  // Load previous
  let prev = [];
  try {
    prev = JSON.parse(fs.readFileSync(SAVE_PATH, "utf-8"));
  } catch {
    prev = [];
  }
  const prevSet = new Set(prev);
  const currSet = new Set(uniqueCurrent);

  const added = uniqueCurrent.filter((a) => !prevSet.has(a));
  const removed = prev.filter((a) => !currSet.has(a));

  console.log(`[sync] Diff — added: ${added.length}, removed: ${removed.length}`);
  if (added.length) console.log("  +", added.slice(0, 5).join(", ") + (added.length > 5 ? "..." : ""));
  if (removed.length) console.log("  -", removed.slice(0, 5).join(", ") + (removed.length > 5 ? "..." : ""));

  if (!WEBHOOK_ID && !ALCHEMY_URL) {
    console.log("[sync] No Alchemy webhook config found; skipping remote update (dry-run mode).");
  } else {
    const prev = (() => { try { return JSON.parse(fs.readFileSync(SAVE_PATH, "utf-8")); } catch { return []; } })();
    const prevSet = new Set(prev);
    const currSet = new Set(uniqueCurrent);
    const toAdd = uniqueCurrent.filter((a) => !prevSet.has(a));
    const toRemove = prev.filter((a) => !currSet.has(a));

    const payload = {
      webhook_id: WEBHOOK_ID,
      addresses_to_add: toAdd,
      addresses_to_remove: toRemove,
    };
    try {
      const res = await fetch(ALCHEMY_URL, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(API_TOKEN ? { "X-Alchemy-Token": API_TOKEN } : {}),
        },
        body: JSON.stringify(payload),
      });
      const body = await res.text();
      if (res.ok) {
        console.log(`[sync] Alchemy webhook updated: HTTP ${res.status} (added=${toAdd.length}, removed=${toRemove.length})`);
      } else {
        console.error(`[sync] Alchemy webhook update failed: HTTP ${res.status} — ${body.slice(0, 200)}`);
      }
    } catch (e) {
      console.error(`[sync] Alchemy webhook update error: ${e.message}`);
    }
  }

  fs.writeFileSync(SAVE_PATH, JSON.stringify(uniqueCurrent, null, 2));
  console.log(`[sync] Cache saved to ${SAVE_PATH}`);
  console.log("[sync] Done.");
}

main().catch((e) => {
  console.error("[sync] Fatal:", e);
  process.exit(1);
});

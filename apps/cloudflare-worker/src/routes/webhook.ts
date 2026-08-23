import type { Context } from "hono";
import type { Env } from "../env";
import { loadConfig } from "../config";
import { PriceOracle } from "../priceOracle";
import { mapNetwork, type AlchemyEvent } from "../normalizer";
import { ingestEvent, drain } from "../pipeline";
import * as repo from "../db";
import type { CuratedWallet } from "../types";

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.replace(/^0x/, "");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.substr(i * 2, 2), 16);
  }
  return out;
}

function bufToHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function verifySignature(
  body: string,
  sig: string | undefined,
  keys: string[],
): Promise<boolean> {
  if (!sig) return false;
  const data = new TextEncoder().encode(body);
  for (const key of keys) {
    try {
      const cryptoKey = await crypto.subtle.importKey(
        "raw",
        hexToBytes(key),
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["sign"],
      );
      const mac = await crypto.subtle.sign("HMAC", cryptoKey, data);
      const computed = "0x" + bufToHex(mac);
      if (computed.toLowerCase() === sig.toLowerCase()) return true;
    } catch {
      /* try next key */
    }
  }
  return false;
}

export async function alchemyWebhook(c: Context) {
  const env = c.env as Env;
  const cfg = loadConfig(env);
  const body = await c.req.text();

  if (cfg.alchemySigningKeys.length) {
    const sig = c.req.header("X-Alchemy-Signature");
    if (!(await verifySignature(body, sig, cfg.alchemySigningKeys))) {
      return c.text("invalid signature", 401);
    }
  }

  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    return c.text("bad json", 400);
  }

  const messages = Array.isArray(payload) ? payload : [payload];
  const db = env.DB;
  const oracle = new PriceOracle(env.KV);

  const wallets = await repo.getCuratedActive(db);
  const byKey = new Map<string, CuratedWallet>();
  for (const w of wallets) byKey.set(`${w.chain}:${w.address}`, w);

  let ingested = 0;
  for (const msg of messages as Array<{ event?: AlchemyEvent } & AlchemyEvent>) {
    const ev: AlchemyEvent = (msg.event as AlchemyEvent) || (msg as AlchemyEvent);
    const chain = mapNetwork(ev.network);
    const addrs = [
      (ev.fromAddress || "").toLowerCase(),
      (ev.toAddress || "").toLowerCase(),
    ];
    let wallet: CuratedWallet | undefined;
    for (const a of addrs) {
      const w = byKey.get(`${chain}:${a}`);
      if (w) {
        wallet = w;
        break;
      }
    }
    if (!wallet) continue;
    if (await ingestEvent(db, ev, wallet, oracle)) ingested++;
  }

  const processed = await drain(db, cfg, 5);
  return c.json({ ok: true, ingested, processed });
}

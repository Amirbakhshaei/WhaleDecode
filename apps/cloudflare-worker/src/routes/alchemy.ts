import { Hono } from "hono";
import type { Env, WhaleActivity, CuratedWallet } from "../types";
import { findCuratedWallet } from "../db";
import { analyzeEvent } from "../llm";
import { sendToChannel } from "../telegramClient";

export const alchemyRouter = new Hono<{ Bindings: Env }>();

function extractActivities(payload: unknown): WhaleActivity[] {
  if (Array.isArray(payload)) return payload as WhaleActivity[];
  const p = payload as Record<string, unknown>;
  if (p && Array.isArray(p.activity)) return p.activity as WhaleActivity[];
  if (p && p.event && Array.isArray((p.event as Record<string, unknown>).activity)) {
    return (p.event as Record<string, unknown>).activity as WhaleActivity[];
  }
  if (p && p.event && Array.isArray(p.event)) return p.event as WhaleActivity[];
  return [];
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case '"': return "&quot;";
      default: return "&#39;";
    }
  });
}

function formatAlert(wallet: CuratedWallet, act: WhaleActivity, analysis: string): string {
  const hash = act.hash ?? "";
  const explorer = hash ? `https://etherscan.io/tx/${hash}` : "";
  const lines = [
    "🐋 <b>WhaleDecode Alert</b>",
    "",
    `<b>Entity:</b> ${escapeHtml(wallet.label)} (${escapeHtml(wallet.chain)})`,
    `<b>From:</b> ${escapeHtml(act.fromAddress ?? "")}`,
    `<b>To:</b> ${escapeHtml(act.toAddress ?? "")}`,
    `<b>Value:</b> ${escapeHtml(act.value ?? "unknown")} ${escapeHtml(act.asset ?? "")}`.trim(),
    "",
    analysis,
  ];
  if (explorer) lines.push("", `<a href="${explorer}">View transaction</a>`);
  return lines.join("\n");
}

async function verifySignature(raw: string, sig: string | null, keys: string): Promise<boolean> {
  if (!sig || !keys) return false;
  const enc = new TextEncoder();
  for (const key of keys.split(",").map((k) => k.trim()).filter(Boolean)) {
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      enc.encode(key),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const signed = await crypto.subtle.sign("HMAC", cryptoKey, enc.encode(raw));
    const hex = Array.from(new Uint8Array(signed))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    if (`0x${hex}` === sig.toLowerCase() || hex === sig.toLowerCase()) return true;
  }
  return false;
}

async function runPipeline(env: Env, activities: WhaleActivity[]): Promise<void> {
  for (const act of activities) {
    const candidates = [act.fromAddress, act.toAddress].filter(Boolean) as string[];
    for (const addr of candidates) {
      const wallet = await findCuratedWallet(env.DB, addr);
      if (!wallet) continue;
      try {
        const analysis = await analyzeEvent(act, wallet, env);
        await sendToChannel(env, formatAlert(wallet, act, analysis));
      } catch (e) {
        console.error("alchemy_alert_failed", { addr, error: String(e) });
      }
      break; // one match per activity is enough
    }
  }
}

alchemyRouter.post("/", async (c) => {
  const raw = await c.req.text();
  const signingKey = c.env.ALCHEMY_WEBHOOK_SIGNING_KEYS;
  const sig = c.req.header("X-Alchemy-Signature") ?? null;
  if (signingKey && sig) {
    const ok = await verifySignature(raw, sig, signingKey);
    if (!ok) return c.json({ success: false, error: "invalid_signature" }, 401);
  }

  let payload: unknown = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }
  const activities = extractActivities(payload);

  c.executionCtx?.waitUntil(
    runPipeline(c.env, activities).catch((e) =>
      console.error("alchemy_pipeline_error", String(e)),
    ),
  );

  return c.json({ success: true, queued: true }, 200);
});

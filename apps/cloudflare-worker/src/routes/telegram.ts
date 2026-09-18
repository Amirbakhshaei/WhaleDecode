import { Hono } from "hono";
import type { Env } from "../types";
import { sendMessage } from "../telegramClient";
import { groqChat } from "../llm";
import {
  addTrackedWallet,
  listTrackedWallets,
  removeTrackedWallet,
} from "../db";

export const telegramRouter = new Hono<{ Bindings: Env }>();

const HELP = [
  "👋 <b>WhaleDecode Bot</b>",
  "",
  "Commands:",
  "• /start — show this help",
  "• /whales — curated watchlist",
  "• /track &lt;0xaddress&gt; — follow a wallet",
  "• /untrack &lt;0xaddress&gt; — stop following",
  "• /status — list your tracked wallets",
  "• /summary — 24h top flows",
  "• /ask &lt;question&gt; — ask on-chain intel",
].join("\n");

const ADDRESS_RE = /^0x[a-fA-F0-9]{40}$/;

telegramRouter.post("/", async (c) => {
  const secret = c.env.TELEGRAM_WEBHOOK_SECRET;
  if (secret) {
    const provided = c.req.header("x-telegram-bot-api-secret-token") ?? new URL(c.req.url).searchParams.get("secret");
    if (provided !== secret) return c.json({ ok: false, error: "invalid_secret" }, 401);
  }
  const update = await c.req.json().catch(() => null);
  const message = update?.message;
  if (!message || typeof message.text !== "string") {
    return c.json({ ok: true }, 200);
  }

  const chatId = message.chat?.id;
  const userId = message.from?.id;
  const rawCmd = message.text.split(" ")[0];
  const cmd = rawCmd.split("@")[0]; // strip bot mention, e.g. /track@WhaleDecodeBot
  const arg = message.text.split(" ")[1]?.trim() ?? "";

  try {
    if (cmd === "/start") {
      await sendMessage(c.env, chatId, HELP);
    } else if (cmd === "/whales") {
      const rows = await c.env.DB.prepare("SELECT label, chain FROM curated_wallets WHERE is_active = 1 ORDER BY quality_score DESC LIMIT 10").all<{ label: string; chain: string }>();
      const list = (rows.results ?? []).map((w) => `• ${w.label} (${w.chain})`).join("\n") || "Watchlist empty.";
      await sendMessage(c.env, chatId, `🐋 <b>Curated whales</b>\n${list}`);
    } else if (cmd === "/summary") {
      const rows = await c.env.DB.prepare("SELECT chain, tx_hash, value_usd FROM candidate_events WHERE created_at >= datetime('now', '-1 day') ORDER BY value_usd DESC LIMIT 5").all<{ chain: string; tx_hash: string; value_usd: number }>();
      const list = (rows.results ?? []).map((r) => `• ${r.chain}: $${Math.round(r.value_usd).toLocaleString("en-US")} <code>${String(r.tx_hash).slice(0, 10)}…</code>`).join("\n") || "No whale flows in the last 24h.";
      await sendMessage(c.env, chatId, `📊 <b>24h summary</b>\n${list}`);
    } else if (cmd === "/status") {
      const tracked = userId ? await listTrackedWallets(c.env.DB, userId) : [];
      const text = tracked.length
        ? `You track ${tracked.length} wallet(s):\n` +
          tracked.map((t) => `• ${t.address}`).join("\n")
        : "You are not tracking any wallets yet. Use /track &lt;address&gt;.";
      await sendMessage(c.env, chatId, text);
    } else if (cmd === "/track") {
      if (!ADDRESS_RE.test(arg)) {
        await sendMessage(c.env, chatId, "Usage: /track &lt;0xaddress&gt;");
      } else if (userId) {
        await addTrackedWallet(c.env.DB, userId, arg);
        await sendMessage(c.env, chatId, `✅ Now tracking ${arg}`);
      }
    } else if (cmd === "/untrack") {
      if (userId && ADDRESS_RE.test(arg)) {
        await removeTrackedWallet(c.env.DB, userId, arg);
        await sendMessage(c.env, chatId, `🗑 Stopped tracking ${arg}`);
      } else {
        await sendMessage(c.env, chatId, "Usage: /untrack &lt;0xaddress&gt;");
      }
    } else if (cmd === "/ask") {
      const question = message.text.slice(rawCmd.length).trim();
      if (!question) {
        await sendMessage(c.env, chatId, "Usage: /ask <your question>");
      } else {
        const answer = await groqChat(
          `You are WhaleDecode, an on-chain intelligence assistant. Answer concisely and accurately:\n${question}`,
          c.env,
        );
        await sendMessage(c.env, chatId, answer);
      }
    } else if (cmd.startsWith("/")) {
      await sendMessage(c.env, chatId, HELP);
    }
  } catch (e) {
    console.error("telegram_cmd_error", String(e));
  }

  return c.json({ ok: true }, 200);
});

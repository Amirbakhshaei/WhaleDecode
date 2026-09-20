import type { Env, WhaleActivity, CuratedWallet } from "./types";
import { guardEventAnalysis, type EventAnalysisResult, type ChatReportResult, type ConsolidatedReport } from "./types/llmSchemas";
import { getPriceUsdc } from "./services/priceOracle";

const GEMINI_FALLBACK = "gemini-3.5-flash-lite";
const GROQ_FALLBACK = "openai/gpt-oss-120b";
export const GROQ_CHEAP_FALLBACK = "openai/gpt-oss-20b";

// ponytail: minimal DexScreener endpoint (no heavy library)
const DEXSCREENER_API = (token: string) => `https://api.dexscreener.com/latest/dex/pairs/ethereum/${token}`;

export interface EnrichedEvent {
  chain: string;
  asset?: string;
  value_usd?: number;
  from_label?: string;
  to_label?: string;
  pool_liquidity_usd?: number | null;
  token_24h_change?: number | null;
  from_address?: string;
  to_address?: string;
  flow_type?: string;
  raw_json?: Record<string, unknown>;
}

export function buildAnalysisPrompt(activity: WhaleActivity, wallet: CuratedWallet): string {
  const amount = activity.value ?? "unknown";
  const asset = activity.asset ?? "ETH";
  const direction = activity.fromAddress === wallet.address ? "OUT" : "IN";
  return [
    `You are WhaleDecode, an on-chain intelligence assistant.`,
    `A tracked whale wallet just had activity.`,
    `Wallet label: ${wallet.label}`,
    `Tags: ${wallet.tags}`,
    `Chain: ${activity.chain ?? wallet.chain}`,
    `Direction: ${direction}`,
    `Amount: ${amount} ${asset}`,
    `Tx hash: ${activity.hash ?? "n/a"}`,
    `From: ${activity.fromAddress ?? "n/a"}`,
    `To: ${activity.toAddress ?? "n/a"}`,
    `Give a concise (<=80 words) analyst note: what the move likely signals and any context worth flagging.`,
  ].join("\n");
}

// Phase 1 Stage 1: Data Gathering (fetch + timeout)
export async function gatherData(eventData: EnrichedEvent, env: Env): Promise<EnrichedEvent> {
  const enriched = { ...eventData };

  // DexScreener liquidity fetch (4s timeout)
  if (enriched.asset && (enriched.asset as string).length > 0) {
    try {
      const tok = enriched.asset.replace(/^0x/, "").toLowerCase();
      const resp = await fetch(DEXSCREENER_API(tok), { signal: AbortSignal.timeout(4000) });
      if (resp.ok) {
        const d = (await resp.json()) as { pairs?: unknown[] };
        const pairs = Array.isArray(d.pairs) ? d.pairs : [];
        if (pairs.length > 0) {
          const p = pairs[0] as Record<string, unknown>;
          enriched.pool_liquidity_usd = (p.liquidity as any)?.usd ?? null;
          enriched.token_24h_change = (p.priceChange as any)?.h24 ?? null;
        }
      }
    } catch (e) {
      // ponytail: degrade gracefully; no crash on missing DEX
      console.error("dexscreener_fetch_failed", String(e));
    }
  }

  // Lightweight RPC balance / metadata stub (failover handled by router phase 2)
  // Hardcoded price oracle enrichment
  if (enriched.asset && !enriched.value_usd && !enriched.raw_json?.value_usd) {
    try {
      const price = await getPriceUsdc(enriched.asset);
      // Approximate value if amount available; otherwise keep 0 for now
      const amount = Number(enriched.raw_json?.token_amount ?? enriched.raw_json?.amount ?? 0);
      if (price > 0) enriched.value_usd = amount * price;
    } catch {
      // degrade
    }
  }

  try {
    const rpcUrl = env.DRPC_URL || "https://ethereum-rpc.publicnode.com";
    const rpcRes = await fetch(rpcUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "eth_getBalance", params: [enriched.from_address ?? "0x0", "latest"], id: 1 }),
      signal: AbortSignal.timeout(4000),
    });
    if (rpcRes.ok) {
      const d = (await rpcRes.json()) as { result?: string };
      // balance available if needed; currently only enrichment
    }
  } catch (e) {
    console.error("rpc_fetch_failed", String(e));
  }

  return enriched;
}

// Phase 1 Stage 2: Smart Money Concepts (SMC Analyst)
export function buildSMCPrompt(enriched: EnrichedEvent): string {
  return `You are a Smart Money Concepts analyst.
Evaluate the whale event below for accumulation/distribution signatures, sweep behavior, and funding-edge patterns.
Use ONLY the data block below.

STRICT RULES:
- NEVER invent addresses, amounts, or percentages not in the block.
- If a figure is missing, state it is unavailable.
- Output exactly this JSON: { "signature": string, "sweep_detected": boolean, "funding_edge": string, "conviction_boost": number 0-100, "reasoning": string }.

EVENT DATA:
- Chain: ${enriched.chain || "Unknown"}
- Asset: ${enriched.asset || "Unknown"}
- USD Value: ${enriched.value_usd ? "$" + enriched.value_usd.toLocaleString() : "Unknown"}
- Sender label: ${enriched.from_label || "Unknown"}
- Receiver label: ${enriched.to_label || "Unknown"}
- Flow type: ${enriched.flow_type || "Unknown"}
- Pool liquidity USD: ${enriched.pool_liquidity_usd ?? "Unavailable"}
- 24h change %: ${enriched.token_24h_change ?? "Unavailable"}
- Sender address (first 10 chars): ${String(enriched.from_address ?? "").slice(0, 10)}
- Receiver address (first 10 chars): ${String(enriched.to_address ?? "").slice(0, 10)}`;
}

export async function smcAnalyst(enriched: EnrichedEvent, env: Env): Promise<{ signature: string; sweep_detected: boolean; funding_edge: string; conviction_boost: number; reasoning: string }> {
  const prompt = buildSMCPrompt(enriched);
  try {
    const result = await geminiAnalyzeWithSchema(prompt, env, "smc");
    return {
      signature: String(result.signature ?? "Unknown"),
      sweep_detected: Boolean(result.sweep_detected ?? false),
      funding_edge: String(result.funding_edge ?? "Unknown"),
      conviction_boost: Math.max(0, Math.min(100, Number(result.conviction_boost ?? 0))),
      reasoning: String(result.reasoning ?? ""),
    };
  } catch (e) {
    console.error("smc_analyst_failed", String(e));
    return { signature: "Unknown", sweep_detected: false, funding_edge: "Unknown", conviction_boost: 0, reasoning: "Fallback: analysis unavailable." };
  }
}

// Phase 1 Stage 3: Consolidated Synthesis (Gemini AI Gateway /compat)
export async function consolidatedSynthesis(smcResult: unknown, eventData: EnrichedEvent, env: Env): Promise<EventAnalysisResult> {
  const prompt = `You are a quantitative on-chain intelligence analyst.
Analyze the transaction based ONLY on verified on-chain parameters below.
STRICT RULES:
1. ZERO raw hex addresses in output. Use resolved labels or macro terms.
2. NEVER invent off-chain mechanics.
3. Classify flow clearly (CEX Outflow / Inflow / Internal / Smart Money).
4. Base every number ONLY on the data block.
5. NEVER output brackets, plus signs, or 'N/A'. Reason qualitatively if absent.

OUTPUT valid JSON exactly with fields: entity_profile, context, impact, conviction_score (0-100 int).

DATA BLOCK:
Chain: ${eventData.chain || "Unknown"}
Asset: ${eventData.asset || "Unknown"}
Value USD: ${eventData.value_usd ?? "Unknown"}
From label: ${eventData.from_label || "Unknown"}
To label: ${eventData.to_label || "Unknown"}
Flow: ${eventData.flow_type || "Unknown"}
Pool liquidity: ${eventData.pool_liquidity_usd ?? "Unavail"}
SMC signature: ${JSON.stringify(smcResult)}`;

  try {
    const raw = await geminiAnalyzeWithSchema(prompt, env, "analysis");
    return guardEventAnalysis(raw);
  } catch (e) {
    console.error("consolidated_synthesis_failed", String(e));
    return { entity_profile: "Analysis unavailable.", context: "Data incomplete.", impact: "Unknown.", conviction_score: 0 };
  }
}

// Phase 1 Stage 4: Aegis Guardrail + Telegram HTML/MarkdownV2 formatter
export function aegisGuardrail(report: EventAnalysisResult, raw?: unknown): ConsolidatedReport {
  const sanitized = {
    entity_profile: String(report.entity_profile ?? "").replace(/[<>\[\]*+]/g, ""),
    context: String(report.context ?? "").replace(/[<>\[\]*+]/g, ""),
    impact: String(report.impact ?? "").replace(/[<>\[\]*+]/g, ""),
    conviction_score: Math.max(0, Math.min(100, Number(report.conviction_score ?? 0))),
  };

  return {
    analysis: sanitized,
    data_summary: `Entity: ${sanitized.entity_profile}. Context: ${sanitized.context}. Impact: ${sanitized.impact}. Conviction: ${sanitized.conviction_score}/100.`,
    conviction_score: sanitized.conviction_score,
    alert_recommendation: sanitized.conviction_score >= 70 ? "CRITICAL ALERT — immediate Telegram dispatch." : sanitized.conviction_score >= 40 ? "WATCH — include in briefing." : "LOW — log only.",
  };
}

export function formatTelegramMarkdownV2(report: ConsolidatedReport): string {
  const a = report.analysis;
  return `<b>WhaleDecode Alert</b>\n\n` +
    `<b>Profile:</b> ${escapeMarkdown(a.entity_profile)}\n` +
    `<b>Context:</b> ${escapeMarkdown(a.context)}\n` +
    `<b>Impact:</b> ${escapeMarkdown(a.impact)}\n` +
    `<b>Conviction:</b> ${a.conviction_score}/100\n` +
    `<b>Summary:</b> ${escapeMarkdown(report.data_summary)}\n` +
    `<i>Recommendation: ${escapeMarkdown(report.alert_recommendation)}</i>`;
}

function escapeMarkdown(s: string): string {
  return s.replace(/[*_\[\]()`]/g, "\\$&").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Main pipeline: Phase 1 full parity
export async function runLLMPipeline(eventData: EnrichedEvent, env: Env): Promise<{ report: ConsolidatedReport; telegramPayload: string; rawAnalysis: EventAnalysisResult }> {
  const enriched = await gatherData(eventData, env);
  const smc = await smcAnalyst(enriched, env);
  const analysis = await consolidatedSynthesis(smc, enriched, env);
  const report = aegisGuardrail(analysis, smc);
  const telegramPayload = formatTelegramMarkdownV2(report);
  return { report, telegramPayload, rawAnalysis: analysis };
}

// Gemini via AI Gateway /compat with BYOK (cf-aig-authorization)
async function geminiAnalyzeWithSchema(prompt: string, env: Env, stage: string): Promise<Record<string, unknown>> {
  const model = (env.LLM_MODEL || GEMINI_FALLBACK).replace(/^google\//, "").replace(/^models\//, "");
  // AI Gateway compatibility endpoint (Cloudflare AI Gateway) — BYOK via cf-aig-authorization
  const gatewayBase = env.AI_GATEWAY_URL || "https://gateway.ai.cloudflare.com/v1";
  const url = `${gatewayBase}/llm/google-ai-studio/${model}`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "cf-aig-authorization": `Bearer ${env.GEMINI_API_KEY}`,
      "cf-aig-model-id": model,
    },
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: { maxOutputTokens: 800, temperature: 0.2, responseMimeType: "application/json" },
    }),
    signal: AbortSignal.timeout(8000),
  });

  if (!res.ok) {
    // Fallback to direct Google endpoint if gateway fails
    const directRes = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
      method: "POST",
      headers: { "x-goog-api-key": env.GEMINI_API_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ contents: [{ role: "user", parts: [{ text: prompt }] }], generationConfig: { maxOutputTokens: 800, temperature: 0.2 } }),
      signal: AbortSignal.timeout(8000),
    });
    if (!directRes.ok) throw new Error(`Gemini ${directRes.status}: ${await directRes.text().catch(() => "")}`);
    const d = (await directRes.json()) as { candidates?: { content?: { parts?: { text?: string }[] } }[] };
    const text = d.candidates?.[0]?.content?.parts?.[0]?.text ?? "{}";
    try { return JSON.parse(text) as Record<string, unknown>; } catch { return { entity_profile: text, context: "", impact: "", conviction_score: 50 }; }
  }

  const d = (await res.json()) as { candidates?: { content?: { parts?: { text?: string }[] } }[] };
  const text = d.candidates?.[0]?.content?.parts?.[0]?.text ?? "{}";
  try { return JSON.parse(text) as Record<string, unknown>; } catch { return { entity_profile: text, context: "", impact: "", conviction_score: 50 }; }
}

export async function analyzeEvent(activity: WhaleActivity, wallet: CuratedWallet, env: Env): Promise<string> {
  const prompt = buildAnalysisPrompt(activity, wallet);
  try {
    const res = await geminiAnalyzeWithSchema(prompt, env, "analyze");
    return JSON.stringify(res);
  } catch (e) {
    console.error("gemini_failed_fallback_groq", String(e));
    return await groqChat(prompt, env);
  }
}

// Backward-compatible exports
export async function geminiAnalyze(prompt: string, env: Env): Promise<string> {
  const res = await geminiAnalyzeWithSchema(prompt, env, "analyze");
  return JSON.stringify(res);
}

export async function groqChat(prompt: string, env: Env, model?: string): Promise<string> {
  const m = model || env.GROQ_MODEL || GROQ_FALLBACK;
  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GROQ_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: m, messages: [{ role: "user", content: prompt }], max_tokens: 500, temperature: 0.3 }),
  });
  if (!res.ok) throw new Error(`Groq ${res.status}: ${await res.text().catch(() => "")}`);
  const d = (await res.json()) as { choices?: { message?: { content?: string } }[] };
  return d.choices?.[0]?.message?.content ?? "";
}

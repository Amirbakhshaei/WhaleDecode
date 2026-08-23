import type { AppConfig } from "./config";
import type { InvestigationResult } from "./types";

const MODEL = "llama-3.3-70b-versatile";

function buildPrompt(event: Record<string, unknown>): string {
  const raw = (event.raw_json as Record<string, unknown>) || {};
  const from = String(raw.from || "unknown");
  const to = String(raw.to || "unknown");
  const sym = String(raw.symbol || raw.asset || "UNKNOWN");
  const amount = Number(raw.amount || 0);
  const valueUsd = Number(raw.value_usd || 0);
  const chain = String(event.chain || "unknown");
  const tx = String(event.tx_hash || "");

  return [
    "You are WhaleDecode, a crypto on-chain intelligence analyst specializing in smart-money / whale flow.",
    "Analyze the following on-chain transfer and return STRICT JSON (no markdown, no commentary).",
    "",
    "Event:",
    `- Chain: ${chain}`,
    `- Asset: ${sym}`,
    `- Amount: ${amount}`,
    `- Approx USD value: $${valueUsd.toLocaleString()}`,
    `- From: ${from}`,
    `- To: ${to}`,
    `- Tx: ${tx}`,
    "",
    "Return JSON with exactly these keys:",
    '- "summary": 1-3 short bullet lines (use "• " prefix per line) of trader-focused SMC intelligence.',
    '- "fundamental_summary": one sentence on the entity / fundamental context.',
    '- "technical_summary": one sentence on technical/flow context.',
    '- "bias_summary": one sentence on directional bias / market impact.',
    '- "risk_score": number 0..1 estimating conviction/importance.',
    '- "is_safe": boolean, true unless the content is malicious/unsafe.',
    '- "thesis": one sentence investment thesis.',
    "",
    'Example: {"summary":"• Accumulation by a known smart wallet\\n• Off-exchange positioning","fundamental_summary":"Entity under analysis.","technical_summary":"Market context unavailable.","bias_summary":"Impact under assessment.","risk_score":0.72,"is_safe":true,"thesis":"Possible accumulation signal."}',
  ].join("\n");
}

function safeJson(text: string): Record<string, unknown> {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start >= 0 && end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1));
    } catch {
      /* fall through */
    }
  }
  return {};
}

export async function investigateEvent(
  event: Record<string, unknown>,
  cfg: AppConfig,
  fetchFn: typeof fetch = fetch,
): Promise<InvestigationResult> {
  const prompt = buildPrompt(event);
  const body = {
    model: MODEL,
    messages: [{ role: "user", content: prompt }],
    response_format: { type: "json_object" },
    temperature: 0.3,
    max_tokens: 700,
  };

  const res = await fetchFn(`${cfg.groqBaseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.groqApiKey}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Groq investigate failed: HTTP ${res.status}`);
  }
  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const content = data.choices?.[0]?.message?.content || "{}";
  const parsed = safeJson(content);

  const risk = Number(parsed.risk_score ?? 0);
  return {
    summary: String(parsed.summary || ""),
    fundamental_summary: String(parsed.fundamental_summary || ""),
    technical_summary: String(parsed.technical_summary || ""),
    bias_summary: String(parsed.bias_summary || ""),
    risk_score: Number.isFinite(risk) ? Math.min(Math.max(risk, 0), 1) : 0,
    is_safe: parsed.is_safe !== false,
    thesis: String(parsed.thesis || ""),
    entity_profile: String(parsed.fundamental_summary || ""),
  };
}

export async function generateBriefing(
  events: Array<Record<string, unknown>>,
  cfg: AppConfig,
  fetchFn: typeof fetch = fetch,
): Promise<string> {
  if (!events.length) return "No notable whale activity in the last 24h.";
  const lines = events.slice(0, 20).map((e) => {
    const raw = (e.raw_json as Record<string, unknown>) || {};
    const label = String(raw.symbol || "UNK");
    const val = Number(raw.value_usd || 0);
    return `- ${label} transfer of $${val.toLocaleString()} on ${e.chain} (score ${Math.round(Number(e.score || 0))})`;
  });
  const prompt =
    "Summarize the day's whale activity in 2-3 short paragraphs. Highlight the most significant flows and patterns.\n\n" +
    lines.join("\n");

  const res = await fetchFn(`${cfg.groqBaseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.groqApiKey}`,
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [{ role: "user", content: prompt }],
      temperature: 0.4,
      max_tokens: 800,
    }),
  });
  if (!res.ok) throw new Error(`Groq briefing failed: HTTP ${res.status}`);
  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  return data.choices?.[0]?.message?.content || "Briefing unavailable.";
}

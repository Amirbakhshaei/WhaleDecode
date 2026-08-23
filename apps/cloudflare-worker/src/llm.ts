import type { Env, WhaleActivity, CuratedWallet } from "./types";

const GEMINI_FALLBACK = "gemini-2.5-flash";
const GROQ_FALLBACK = "llama-3.3-70b-versatile";

export function buildAnalysisPrompt(
  activity: WhaleActivity,
  wallet: CuratedWallet
): string {
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

export async function geminiAnalyze(
  prompt: string,
  env: Env
): Promise<string> {
  const model = (env.LLM_MODEL || GEMINI_FALLBACK)
    .replace(/^google\//, "")
    .replace(/^models\//, "");
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
    {
      method: "POST",
      headers: {
        "x-goog-api-key": env.GEMINI_API_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        contents: [{ role: "user", parts: [{ text: prompt }] }],
        generationConfig: { maxOutputTokens: 400, temperature: 0.3 },
      }),
    }
  );
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Gemini ${res.status}: ${t.slice(0, 200)}`);
  }
  const data = (await res.json()) as {
    candidates?: { content?: { parts?: { text?: string }[] } }[];
  };
  return (data.candidates?.[0]?.content?.parts?.[0]?.text ?? "").trim();
}

export async function groqChat(
  prompt: string,
  env: Env,
  model?: string
): Promise<string> {
  const m = model || env.GROQ_MODEL || GROQ_FALLBACK;
  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GROQ_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: m,
      messages: [{ role: "user", content: prompt }],
      max_tokens: 500,
      temperature: 0.3,
    }),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Groq ${res.status}: ${t.slice(0, 200)}`);
  }
  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  return (data.choices?.[0]?.message?.content ?? "").trim();
}

export async function analyzeEvent(
  activity: WhaleActivity,
  wallet: CuratedWallet,
  env: Env
): Promise<string> {
  const prompt = buildAnalysisPrompt(activity, wallet);
  try {
    return await geminiAnalyze(prompt, env);
  } catch (e) {
    console.error("gemini_failed_fallback_groq", String(e));
    return await groqChat(prompt, env);
  }
}

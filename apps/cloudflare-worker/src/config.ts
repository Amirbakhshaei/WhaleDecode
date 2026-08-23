import type { Env } from "./env";

export interface AppConfig {
  botToken: string;
  botUsername: string;
  channelChatId: string;
  channelPublishEnabled: boolean;
  groqApiKey: string;
  groqBaseUrl: string;
  geminiApiKey: string;
  alchemySigningKeys: string[];
  alchemyAuthToken: string;
}

export function loadConfig(env: Env): AppConfig {
  const signingRaw = env.ALCHEMY_WEBHOOK_SIGNING_KEYS || "";
  const alchemySigningKeys = signingRaw
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);

  return {
    botToken: env.BOT_TOKEN || "",
    botUsername: (env.BOT_USERNAME || "whaledecodebot").replace(/^@/, ""),
    channelChatId: env.CHANNEL_CHAT_ID || "",
    channelPublishEnabled: (env.CHANNEL_PUBLISH_ENABLED || "false") === "true",
    groqApiKey: env.GROQ_API_KEY || "",
    groqBaseUrl: env.GROQ_BASE_URL || "https://api.groq.com/openai/v1",
    geminiApiKey: env.GEMINI_API_KEY || "",
    alchemySigningKeys,
    alchemyAuthToken: env.ALCHEMY_NOTIFY_TOKEN || env.ALCHEMY_AUTH_TOKEN || "",
  };
}

/// <reference types="@cloudflare/workers-types" />

export interface Env {
  DB: D1Database;
  KV: KVNamespace;

  // Secrets (set via `wrangler secret put` in production; see .dev.vars for local)
  BOT_TOKEN: string;
  BOT_USERNAME: string;
  CHANNEL_CHAT_ID: string;
  GROQ_API_KEY: string;
  GROQ_BASE_URL: string;
  GEMINI_API_KEY: string;
  ALCHEMY_WEBHOOK_SIGNING_KEYS: string;
  ALCHEMY_AUTH_TOKEN: string;
  ALCHEMY_NOTIFY_TOKEN: string;

  // Public / non-secret config
  CHANNEL_PUBLISH_ENABLED?: string;
}

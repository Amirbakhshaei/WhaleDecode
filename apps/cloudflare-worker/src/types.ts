// Cloudflare environment bindings + shared types.

export interface Env {
  DB: D1Database;
  DRPC_URL: string;
  BOT_TOKEN: string;
  CHANNEL_CHAT_ID: string;
  GEMINI_API_KEY: string;
  GROQ_API_KEY: string;
  GROQ_API_KEY_SECONDARY?: string;
  ALCHEMY_WEBHOOK_SIGNING_KEYS?: string;
  LLM_MODEL?: string;
  GROQ_MODEL?: string;
  TELEGRAM_BOT_USERNAME?: string;
}

export interface CuratedWallet {
  address: string;
  chain: string;
  label: string;
  tags: string;
}

export interface WhaleActivity {
  fromAddress?: string;
  toAddress?: string;
  value?: string;
  asset?: string;
  hash?: string;
  chain?: string;
  [key: string]: unknown;
}

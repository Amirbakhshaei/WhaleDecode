// Cloudflare environment bindings + shared types.

export interface Env {
  DB: D1Database;
  DRPC_URL: string;
  BOT_TOKEN: string;
  CHANNEL_CHAT_ID: string;
  GEMINI_API_KEY: string;
  DRPC_URL_SECONDARY?: string;
  GROQ_API_KEY: string;
  GROQ_API_KEY_SECONDARY?: string;
  ALCHEMY_WEBHOOK_SIGNING_KEYS?: string;
  LLM_MODEL?: string;
  AI_GATEWAY_URL?: string;
  GROQ_MODEL?: string;
  GROQ_CHEAP_MODEL?: string;
  TELEGRAM_BOT_USERNAME?: string;
  TELEGRAM_BOT_TOKEN?: string;
  TELEGRAM_CHANNEL_ID?: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  ALCHEMY_WEBHOOK_SIGNING_KEY?: string;
  ALCHEMY_SIGNING_KEY_ETH?: string;
  ALCHEMY_SIGNING_KEY_ARB?: string;
  ALCHEMY_SIGNING_KEY_BASE?: string;
  HELIUS_WEBHOOK_SECRET?: string;
  CURATED_WALLETS_JSON?: string;
  DEEP_ENGINE_URL?: string;
  DEEP_ENGINE_SECRET?: string;
}

export interface CuratedWallet {
  address: string;
  chain: string;
  label: string;
  tags: string;
  is_exchange?: number;
  is_mev?: number;
  is_active?: number;
  quality_score?: number;
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

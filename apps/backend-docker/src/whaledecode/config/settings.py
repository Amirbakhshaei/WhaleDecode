import os
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    ENV: Literal["dev", "stage", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    ADMIN_USER_IDS: list[int] = []
    PORT: int = 8080
    ALCHEMY_SIGNING_KEY_ETH: SecretStr | None = None
    ALCHEMY_SIGNING_KEY_ARB: SecretStr | None = None
    ALCHEMY_SIGNING_KEY_BASE: SecretStr | None = None
    ALCHEMY_AUTH_TOKEN: SecretStr | None = None
    ALCHEMY_NOTIFY_TOKEN: SecretStr | None = None
    # Single webhook sync credentials (Notify API Auth Token + target webhook id).
    ALCHEMY_API_KEY: SecretStr | None = None
    ALCHEMY_WEBHOOK_ID: str = ""
    ALCHEMY_WEBHOOK_ID_ETH: str = ""
    ALCHEMY_WEBHOOK_ID_ARB: str = ""
    ALCHEMY_WEBHOOK_ID_BASE: str = ""

    # Value Threshold & Noise Filter — global USD floor; events below this are
    # dropped at ingestion (no candidate_event, no LLM synthesis, no alert).
    MIN_ALERT_USD_THRESHOLD: float = 50_000.0

    # Curated-wallet sources
    DUNE_API_KEY: SecretStr | None = None  # live Dune Spellbook labels (free tier, then falls back to static seed)

    # Edge Intelligence
    ZERION_API_KEY: SecretStr | None = None  # Module 1 cold-start PnL fallback (free tier: 2K req/day)
    ZEROX_API_KEY: SecretStr | None = None  # Module 4 0x Swap API v2 quotes
    SWAP_FEE_BPS: int = 80  # Module 4 value capture (80 bps = 0.8%)
    SWAP_FEE_RECIPIENT: str = ""  # fee-refundable address registered with the aggregator

    @property
    def webhook_signing_keys(self) -> list[str]:
        """Return the configured per-chain Alchemy signing keys (ETH/ARB/BASE)."""
        keys: list[str] = []
        for secret in (
            self.ALCHEMY_SIGNING_KEY_ETH,
            self.ALCHEMY_SIGNING_KEY_ARB,
            self.ALCHEMY_SIGNING_KEY_BASE,
        ):
            if secret:
                keys.append(secret.get_secret_value())
        return keys

    # Telegram
    BOT_TOKEN: SecretStr
    BOT_USERNAME: str = "whaledecodebot"
    WEBHOOK_URL: str | None = None
    WEBHOOK_SECRET: SecretStr | None = None

    # Database
    DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 10

    # Redis (optional — used for alert dedup; worker uses pure asyncio without Redis)
    REDIS_URL: str = ""
    REDIS_MAX_CONNECTIONS: int = 20

    # LLM — Gemini (heavy reasoning / briefing)
    GEMINI_API_KEY: SecretStr | None = None
    MODEL_HEAVY_REASONING: str = "gemini-3.5-flash-lite"

    # LLM — Groq (structured data & fast chat)
    GROQ_API_KEY: SecretStr
    GROQ_API_KEY_SECONDARY: SecretStr | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    MODEL_STRUCTURED_DATA: str = "openai/gpt-oss-120b"
    MODEL_FAST_CHAT: str = "openai/gpt-oss-120b"
    DEFAULT_CHEAP_MODEL: str = "openai/gpt-oss-20b"
    DEFAULT_STRONG_MODEL: str = "openai/gpt-oss-120b"
    # llama-3.3-70b-versatile was shut down by Groq on 2026-08-16; the official
    # replacement is openai/gpt-oss-120b (https://console.groq.com/docs/deprecations).
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    MAX_COST_PER_RUN_USD: float = 0.03

    # LLM — /ask bot fallback model ID (Groq-hosted gpt-oss-20b)
    MODEL_ASK: str = "openai/gpt-oss-20b"

    # Fallback LLMs
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    OPENROUTER_API_KEY: SecretStr | None = None

    # Chain Providers (per-chain RPC URLs; at least one needed for real data)
    ETH_RPC_URL: str | None = None
    ARB_RPC_URL: str | None = None
    BASE_RPC_URL: str | None = None
    POLL_INTERVAL_SECONDS: int = 15
    POLL_BATCH_SIZE: int = 50
    REORG_SAFE_BLOCKS: int = 64
    MAX_GET_LOGS_BLOCK_RANGE: dict[str, int] = {"Ethereum": 5, "Base": 30, "Arbitrum": 100}

    # Targeted failover poller (free public RPCs; replaces paid webhooks).
    # Comma-separated endpoint lists — the router rotates on 429/502/timeout.
    TARGETED_POLLER_ENABLED: bool = True
    TARGETED_RPC_COOLDOWN_SECONDS: float = 300.0
    # Aggregated net USD per transaction required before ingestion (the
    # webhook path's whale floor, now applied at the poller).
    TARGETED_MIN_TX_USD: float = 50_000.0
    ETH_PUBLIC_RPC_URLS: str = "https://eth.merkle.io,https://ethereum-rpc.publicnode.com,https://eth.llamarpc.com,https://1rpc.io/eth,https://rpc.payload.de"
    BASE_PUBLIC_RPC_URLS: str = "https://mainnet.base.org,https://base-rpc.publicnode.com,https://base.llamarpc.com,https://1rpc.io/base"
    ARB_PUBLIC_RPC_URLS: str = "https://arb1.arbitrum.io/rpc,https://arbitrum-one-rpc.publicnode.com,https://arbitrum.llamarpc.com,https://1rpc.io/arb"
    SOL_PUBLIC_RPC_URLS: str = "https://api.mainnet-beta.solana.com,https://solana-rpc.publicnode.com"

    # Alert Pipeline
    ALERT_SCORE_THRESHOLD: float = 0.50
    ACCUMULATION_WINDOW_SECONDS: int = 86400
    FREE_ALERT_BATCH_INTERVAL_MINUTES: int = 60
    PAID_ALERT_BATCH_INTERVAL_SECONDS: int = 5
    MIN_INVESTIGATION_SCORE: float = 0.65
    MIN_INVESTIGATION_VALUE_USD: float = 50_000.0

    # Channel Publishing
    TELEGRAM_CHANNEL_ID: str | None = None
    CHANNEL_CHAT_ID: str | None = None
    CHANNEL_PUBLISH_ENABLED: bool = False
    CHANNEL_MAX_DAILY: int = 20

    # Content
    DISCLAIMER_TEXT: str = "⚠️ Not financial advice. DYOR. Data may be delayed or inaccurate."

    # Billing
    FREE_PLAN_CHAT_DAILY: int = 5
    PAID_PLAN_CHAT_DAILY: int = 50
    FREE_MAX_WALLETS: int = 3
    TELEGRAM_STARS_ENABLED: bool = False
    CRYPTO_PAYMENT_ADDRESS: str | None = None

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    SENTRY_DSN: SecretStr | None = None
    ENVIRONMENT: str = "production"

    # LangSmith (optional — enables tracing for LangChain/LangGraph)
    LANGSMITH_TRACING: bool = True
    LANGSMITH_ENDPOINT: str | None = None
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_PROJECT: str = "WhaleDecode"

    def inject_langsmith_env(self) -> None:
        """Push LangSmith vars into os.environ so LangChain auto-traces."""
        env_map = {
            "LANGSMITH_TRACING": "true" if self.LANGSMITH_TRACING else "false",
            "LANGSMITH_PROJECT": self.LANGSMITH_PROJECT,
        }
        if self.LANGSMITH_ENDPOINT:
            env_map["LANGSMITH_ENDPOINT"] = self.LANGSMITH_ENDPOINT
        if self.LANGSMITH_API_KEY:
            env_map["LANGSMITH_API_KEY"] = self.LANGSMITH_API_KEY
        for k, v in env_map.items():
            os.environ[k] = v

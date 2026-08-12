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
    PORT: int = 8000
    ALCHEMY_WEBHOOK_SIGNING_KEY: SecretStr | None = None
    ALCHEMY_WEBHOOK_SIGNING_KEYS: str = ""
    ALCHEMY_AUTH_TOKEN: SecretStr | None = None

    @property
    def webhook_signing_keys(self) -> list[str]:
        """Return list of signing keys from ALCHEMY_WEBHOOK_SIGNING_KEYS (comma-separated),
        falling back to the single ALCHEMY_WEBHOOK_SIGNING_KEY if provided."""
        if self.ALCHEMY_WEBHOOK_SIGNING_KEYS:
            return [k.strip() for k in self.ALCHEMY_WEBHOOK_SIGNING_KEYS.split(",") if k.strip()]
        if self.ALCHEMY_WEBHOOK_SIGNING_KEY:
            return [self.ALCHEMY_WEBHOOK_SIGNING_KEY.get_secret_value()]
        return []

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
    MODEL_STRUCTURED_DATA: str = "llama-3.3-70b-versatile"
    MODEL_FAST_CHAT: str = "llama-3.1-8b-instant"
    DEFAULT_CHEAP_MODEL: str = "llama-3.1-8b-instant"
    DEFAULT_STRONG_MODEL: str = "llama-3.3-70b-versatile"
    MAX_COST_PER_RUN_USD: float = 0.03

    # Fallback LLMs
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    OPENROUTER_API_KEY: SecretStr | None = None

    # Chain Providers (per-chain RPC URLs; at least one needed for real data)
    ETH_RPC_URL: str | None = None
    ARB_RPC_URL: str | None = None
    BASE_RPC_URL: str | None = None
    POLL_INTERVAL_SECONDS: int = 30
    POLL_BATCH_SIZE: int = 50
    REORG_SAFE_BLOCKS: int = 64
    MAX_GET_LOGS_BLOCK_RANGE: dict[str, int] = {"Ethereum": 5, "Base": 30, "Arbitrum": 100}

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

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

    # Telegram
    BOT_TOKEN: SecretStr
    WEBHOOK_URL: str | None = None
    WEBHOOK_SECRET: SecretStr | None = None

    # Database
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 10

    # Redis (optional — used for alert dedup; worker uses pure asyncio without Redis)
    REDIS_URL: str = ""
    REDIS_MAX_CONNECTIONS: int = 20

    # LLM (Groq)
    GROQ_API_KEY: SecretStr
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    DEFAULT_CHEAP_MODEL: str = "llama-3.1-8b-instant"
    DEFAULT_STRONG_MODEL: str = "llama-3.3-70b-versatile"
    MAX_COST_PER_RUN_USD: float = 0.03

    # Fallback LLMs
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    OPENROUTER_API_KEY: SecretStr | None = None

    # Chain Providers
    CHAIN_PROVIDER: str = "drpc"
    DRPC_API_KEY: SecretStr | None = None
    DRPC_BASE_URL: str = "https://rpc.drpc.org"
    POLL_INTERVAL_SECONDS: int = 30
    POLL_BATCH_SIZE: int = 50
    REORG_SAFE_BLOCKS: int = 64

    # Alert Pipeline
    ALERT_SCORE_THRESHOLD: float = 0.50
    FREE_ALERT_BATCH_INTERVAL_MINUTES: int = 60
    PAID_ALERT_BATCH_INTERVAL_SECONDS: int = 5

    # Billing
    FREE_PLAN_CHAT_DAILY: int = 5
    PAID_PLAN_CHAT_DAILY: int = 50
    FREE_MAX_WALLETS: int = 3
    TELEGRAM_STARS_ENABLED: bool = False
    CRYPTO_PAYMENT_ADDRESS: str | None = None

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    SENTRY_DSN: SecretStr | None = None

"""Pre-launch smoke tests: DB, LLM engine, Telegram bot — one command.

Usage: poetry run python scripts/smoke_test_pipeline.py
"""
import asyncio
import os
import sys

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"


def _load_dotenv() -> None:
    """Populate os.environ from ../.env (repo root) without a dotenv dependency."""
    # apps/backend-docker/scripts/ -> repo root is three levels up
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def run_checks() -> None:
    print("🚀 Starting WhaleDecode Pre-Launch Smoke Tests...\n")
    failures: list[str] = []

    # 1. Database connectivity + active curated wallets
    db_url = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://", 1)
    if not db_url:
        failures.append("DATABASE_URL not set")
        print("❌ [Database] DATABASE_URL is not set")
    else:
        engine = create_async_engine(db_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                res = await conn.execute(
                    text(
                        "SELECT upper(chain), count(*) FROM curated_wallets "
                        "WHERE is_monitored_active=TRUE GROUP BY upper(chain);"
                    )
                )
                counts = dict(res.fetchall())
            print(f"✅ [Database] Active Curated Wallets: {counts}")
            if counts.get("ETH", 0) == 0:
                failures.append("No active ETH wallets found!")
        except Exception as e:  # noqa: BLE001
            failures.append(f"Database check failed: {e}")
            print(f"❌ [Database] {e}")
        finally:
            await engine.dispose()

    # 2. LLM model connectivity (Groq)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": os.getenv("GROQ_MODEL", GROQ_DEFAULT_MODEL),
                        "messages": [{"role": "user", "content": "Ping"}],
                        "max_tokens": 5,
                    },
                )
                assert resp.status_code == 200, f"{resp.status_code} - {resp.text[:200]}"
            print(f"✅ [LLM Engine] Model {os.getenv('GROQ_MODEL', GROQ_DEFAULT_MODEL)} is responsive.")
        except Exception as e:  # noqa: BLE001
            failures.append(f"Groq check failed: {e}")
            print(f"❌ [LLM Engine] {e}")
    else:
        print("⏭️ [LLM Engine] GROQ_API_KEY not set — skipped")

    # 3. Telegram bot connectivity (project convention: BOT_TOKEN)
    bot_token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                assert resp.status_code == 200, resp.text[:200]
            bot_info = resp.json().get("result", {})
            print(f"✅ [Telegram Bot] Connected as @{bot_info.get('username')}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"Telegram bot check failed: {e}")
            print(f"❌ [Telegram Bot] {e}")
    else:
        print("⏭️ [Telegram Bot] BOT_TOKEN not set — skipped")

    if failures:
        print("\n💀 SMOKE TESTS FAILED:")
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)

    print("\n🎉 ALL PRE-LAUNCH SMOKE TESTS PASSED!")


if __name__ == "__main__":
    _load_dotenv()
    asyncio.run(run_checks())

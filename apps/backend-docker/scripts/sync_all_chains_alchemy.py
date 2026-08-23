import asyncio
import os
import sys
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

# Search standard .env locations
for path in [".env", "apps/backend-docker/.env", "/app/.env"]:
    if os.path.exists(path):
        load_dotenv(path)
        break
else:
    load_dotenv()

ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY") or os.getenv("ALCHEMY_AUTH_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://")

if not ALCHEMY_API_KEY:
    print("❌ ERROR: ALCHEMY_API_KEY is not set.")
    sys.exit(1)

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL is not set.")
    sys.exit(1)

# Railway's public Postgres proxy requires TLS; asyncpg uses the `ssl` kwarg
# (psycopg's `sslmode` is rejected). Internal/localhost URLs skip this.
_ssl_required = "localhost" not in DATABASE_URL and "127.0.0.1" not in DATABASE_URL

WEBHOOK_MAP = {
    "ETH": os.getenv("ALCHEMY_WEBHOOK_ID_ETH", "wh_w3gp4gipi8x5xive"),
    "BASE": os.getenv("ALCHEMY_WEBHOOK_ID_BASE", "wh_ka1jzrw7el822z1c"),
    "ARB": os.getenv("ALCHEMY_WEBHOOK_ID_ARB", "wh_nyllnmayk2nzgze0"),
}

async def replace_chain_addresses(client: httpx.AsyncClient, chain: str, target_addrs: list[str]):
    webhook_id = WEBHOOK_MAP.get(chain)
    if not webhook_id:
        print(f"⚠️ No Webhook ID configured for {chain}")
        return

    print(f"[{chain}] Replacing all addresses with {len(target_addrs)} target wallets...")

    # PUT atomically replaces the entire address list
    url = "https://dashboard.alchemy.com/api/update-webhook-addresses"
    resp = await client.put(
        url,
        headers={"X-Alchemy-Token": ALCHEMY_API_KEY, "Content-Type": "application/json"},
        json={
            "webhook_id": webhook_id,
            "addresses": target_addrs,
        },
    )

    if resp.status_code == 200:
        print(f"✅ [{chain}] Overwrite successful! Monitored count is now {len(target_addrs)}.")
    else:
        print(f"❌ [{chain}] Overwrite failed: {resp.status_code} - {resp.text}")

async def main():
    engine = create_async_engine(DATABASE_URL, connect_args={"ssl": "require"} if _ssl_required else {})

    # 1. Fetch active targets per chain from Postgres
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT upper(chain) as chain, lower(address) as address
            FROM curated_wallets
            WHERE is_monitored_active = TRUE;
        """))
        rows = result.fetchall()

    chain_targets: dict[str, list[str]] = {"ETH": [], "BASE": [], "ARB": []}
    for row in rows:
        chain = row.chain
        if chain in chain_targets:
            chain_targets[chain].append(row.address)

    # 2. Atomically replace each chain's webhook address list
    async with httpx.AsyncClient(timeout=20.0) as client:
        for chain, addrs in chain_targets.items():
            await replace_chain_addresses(client, chain, addrs)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())

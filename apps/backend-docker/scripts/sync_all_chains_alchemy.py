import asyncio
import os
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

load_dotenv("apps/backend-docker/.env")

ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://")

WEBHOOK_MAP = {
    "ETH": os.getenv("ALCHEMY_WEBHOOK_ID_ETH", "wh_w3gp4gipi8x5xive"),
    "BASE": os.getenv("ALCHEMY_WEBHOOK_ID_BASE", "wh_ka1jzrw7el822z1c"),
    "ARB": os.getenv("ALCHEMY_WEBHOOK_ID_ARB", "wh_nyllnmayk2nzgze0"),
}

async def fetch_current_alchemy_addrs(client: httpx.AsyncClient, webhook_id: str) -> set[str]:
    url = f"https://dashboard.alchemy.com/api/webhook-addresses?webhook_id={webhook_id}"
    resp = await client.get(url, headers={"X-Alchemy-Token": ALCHEMY_API_KEY})
    if resp.status_code == 200:
        return set(addr.lower() for addr in resp.json().get("addresses", []))
    print(f"❌ Error fetching {webhook_id}: {resp.status_code} {resp.text}")
    return set()

async def sync_chain(client: httpx.AsyncClient, chain: str, target_addrs: set[str]):
    webhook_id = WEBHOOK_MAP.get(chain)
    if not webhook_id:
        print(f"⚠️ No Webhook ID configured for {chain}")
        return

    current_addrs = await fetch_current_alchemy_addrs(client, webhook_id)
    to_add = list(target_addrs - current_addrs)
    to_remove = list(current_addrs - target_addrs)

    print(f"[{chain}] Current: {len(current_addrs)} | Target: {len(target_addrs)} | Adding: {len(to_add)} | Removing: {len(to_remove)}")

    if not to_add and not to_remove:
        print(f"✅ [{chain}] Already in sync.")
        return

    url = "https://dashboard.alchemy.com/api/update-webhook-addresses"
    resp = await client.patch(
        url,
        headers={"X-Alchemy-Token": ALCHEMY_API_KEY, "Content-Type": "application/json"},
        json={
            "webhook_id": webhook_id,
            "addresses_to_add": to_add,
            "addresses_to_remove": to_remove,
        },
    )

    if resp.status_code == 200:
        print(f"✅ [{chain}] Successfully synced to Alchemy!")
    else:
        print(f"❌ [{chain}] Sync failed: {resp.status_code} {resp.text}")

async def main():
    engine = create_async_engine(DATABASE_URL)
    
    # 1. Fetch active targets per chain from Postgres
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT upper(chain) as chain, lower(address) as address
            FROM curated_wallets
            WHERE is_monitored_active = TRUE;
        """))
        rows = result.fetchall()

    chain_targets: dict[str, set[str]] = {"ETH": set(), "BASE": set(), "ARB": set()}
    for row in rows:
        chain = row.chain
        if chain in chain_targets:
            chain_targets[chain].add(row.address)

    # 2. Sync each webhook via Alchemy API
    async with httpx.AsyncClient(timeout=20.0) as client:
        for chain, addrs in chain_targets.items():
            await sync_chain(client, chain, addrs)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())

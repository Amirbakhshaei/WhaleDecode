import asyncio
import os
import ssl
import sys
import asyncpg
from dotenv import load_dotenv

load_dotenv(".env")
raw_url = os.getenv("DATABASE_URL", "")

if not raw_url:
    print("❌ ERROR: DATABASE_URL not found in .env or environment variables.")
    sys.exit(1)

# Normalize URL for asyncpg
db_url = raw_url.replace("postgresql+asyncpg://", "postgresql://").split("?")[0]
output_file = "../cloudflare-worker/pg_curated_seed.sql"

async def export():
    print("🔌 Connecting to PostgreSQL via asyncpg...")
    
    # Configure SSL context for Railway public proxy
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        conn = await asyncpg.connect(db_url, ssl=ssl_ctx)
    except Exception:
        # Fallback without SSL if connecting locally
        conn = await asyncpg.connect(db_url)

    print("📦 Querying curated_wallets table...")
    rows = await conn.fetch(
        "SELECT address, chain, label, category, quality_score FROM curated_wallets WHERE is_active = TRUE;"
    )

    lines = []
    for r in rows:
        addr = str(r["address"]).lower().strip()
        chain = str(r["chain"]).strip()
        label = str(r["label"] or "").replace("'", "''").strip()
        category = str(r["category"] or "Smart Money").replace("'", "''").strip()
        score = float(r["quality_score"] or 85.0)

        lines.append(
            f"INSERT OR REPLACE INTO curated_wallets (address, chain, label, category, quality_score) VALUES ('{addr}', '{chain}', '{label}', '{category}', {score});"
        )

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ Successfully exported {len(lines)} entities to {output_file}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(export())

"""Extract high-signal trigger wallets for Alchemy webhook registration.

Active Triggers vs. Passive Attribution strategy:
  * Active Triggers (Alchemy webhook) monitor ONLY low-velocity, high-conviction
    entities (Smart Money / Notable Whale, quality_score >= 80). High-frequency
    infrastructure (CEX, Bridges, DEX, Dao) is never registered — retail traffic
    would vaporize our monthly Compute Units.
  * Passive Attribution (Postgres) keeps all 2,400+ labels; counterparties are
    resolved locally when a whale moves funds.

Run:  poetry run python scripts/extract_active_wallets.py
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from whaledecode.adapters.db.session import create_session_factory
from whaledecode.config.settings import Settings

logger = logging.getLogger(__name__)

# Resolve data/ next to this script regardless of cwd.
_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "alchemy_webhook_wallets.json"
_MAX_WALLETS = 350

_QUERY = text(
    """
    SELECT lower(address) AS address, chain, label, category, quality_score
    FROM curated_wallets
    WHERE is_active = TRUE
      AND category IN ('Smart Money', 'Notable Whale')
      AND category NOT IN ('Bridge', 'Exchange', 'CEX Reserve', 'DEX', 'Infrastructure', 'Dao')
      AND quality_score >= 80.0
    ORDER BY quality_score DESC
    LIMIT :limit;
    """
)


async def extract(limit: int = _MAX_WALLETS) -> list[dict]:
    """Query curated_wallets for high-conviction, low-velocity trigger wallets."""
    settings = Settings()
    factory = create_session_factory(settings)
    async with factory() as session:
        result = await session.execute(_QUERY, {"limit": limit})
        rows = result.mappings().all()
    return [
        {
            "address": str(r["address"]).lower().strip(),
            "chain": str(r["chain"]),
            "label": str(r["label"] or ""),
            "category": str(r["category"] or ""),
            "quality_score": float(r["quality_score"]),
        }
        for r in rows
    ]


def _write_export(wallets: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Dedup by lowercase address; keep the highest-score row (already ordered DESC).
    seen: dict[str, dict] = {}
    for w in wallets:
        seen.setdefault(w["address"], w)
    path.write_text(json.dumps(list(seen.values()), indent=2), encoding="utf-8")


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    wallets = await extract()
    _write_export(wallets, _OUTPUT_PATH)

    breakdown = Counter(w["category"] for w in wallets)
    logger.info("Exported %d trigger wallets to %s", len(wallets), _OUTPUT_PATH)
    for category, count in breakdown.most_common():
        logger.info("  %-16s %d", category, count)
    print(f"\nTotal exported: {len(wallets)}  |  File: {_OUTPUT_PATH}")
    print("Breakdown by category:")
    for category, count in breakdown.most_common():
        print(f"  {category}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

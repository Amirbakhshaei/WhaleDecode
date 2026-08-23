"""Active webhook rotation: keep exactly the top 300 high-conviction wallets on Alchemy.

The Alchemy Address Activity webhook is a precious, finite CU budget. We never
register high-velocity infrastructure (CEX sweepers, bridges, DEX routers).
Instead, every 24h we re-select the 300 best-scoring active entities — applying
a velocity decay penalty to noisy wallets — diff them against what Alchemy
currently tracks, and PATCH only the delta. ``is_monitored_active`` in Postgres
is reconciled atomically so the two sources of truth never drift.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.config.settings import Settings
from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

_BASE_URL = "https://dashboard.alchemy.com/api"
_BATCH = 500

# Per-chain seat quotas so a deep Ethereum pool can't crowd out ARB/BASE.
# Tuned to the 300-wallet budget: 180 ETH + 60 ARB + 60 BASE.
_CHAIN_QUOTAS = {"ETH": 180, "ARB": 60, "BASE": 60}

# Balanced selection via a CTE + window function: rank within each chain by
# (quality_score * velocity_penalty) DESC, then take the top N per chain. This
# prevents a large Ethereum pool from starving L2 coverage — the previous global
# ORDER BY ... LIMIT 300 picked almost all ETH and left ARB/BASE under-monitored.
# Category lists are code constants inlined into the SQL; chain seat quotas are
# scalar binds. ``velocity_penalty`` is carried through the CTE so the outer
# ORDER BY can resolve it (it is ranked on but not projected).
_SELECT_TOP = text(
    """
    WITH ranked AS (
        SELECT
            lower(address) AS address,
            upper(chain) AS chain,
            quality_score,
            category,
            velocity_penalty,
            ROW_NUMBER() OVER (
                PARTITION BY upper(chain)
                ORDER BY (quality_score * velocity_penalty) DESC
            ) AS rn
        FROM curated_wallets
        WHERE is_active = TRUE
          AND category IN ('Smart Money', 'Notable Whale', 'VC Fund', 'Kol Trader')
          AND category NOT IN ('Bridge', 'Exchange', 'CEX Reserve', 'DEX', 'Infrastructure', 'Dao')
          AND tx_count_30d < 600
    )
    SELECT address, chain, quality_score, category
    FROM ranked
    WHERE (chain = 'ETH' AND rn <= :eth_limit)
       OR (chain = 'ARB' AND rn <= :arb_limit)
       OR (chain = 'BASE' AND rn <= :base_limit)
    ORDER BY (quality_score * velocity_penalty) DESC
    LIMIT :total_limit;
    """
)


class WebhookRotationService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        webhook_id: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        raw = auth_token or settings.ALCHEMY_API_KEY or settings.ALCHEMY_NOTIFY_TOKEN or settings.ALCHEMY_AUTH_TOKEN
        self.auth_token = raw.get_secret_value() if hasattr(raw, "get_secret_value") else (raw or "")
        self.webhook_id = webhook_id or settings.ALCHEMY_WEBHOOK_ID or settings.ALCHEMY_WEBHOOK_ID_ETH

    # -- Alchemy Notify API ---------------------------------------------------

    async def get_currently_monitored_on_alchemy(self) -> set[str]:
        """Lowercased set of addresses currently tracked by the webhook."""
        if not self.auth_token or not self.webhook_id:
            logger.warning("webhook_rotation_no_credentials")
            return set()
        headers = {"X-Alchemy-Token": self.auth_token}
        client = HttpClientManager.get_client("alchemy", timeout=30.0)
        addresses: list[str] = []
        url: str | None = f"{_BASE_URL}/webhook-addresses"
        while url:
            resp = await client.get(url, headers=headers, params={"webhook_id": self.webhook_id})
            if not resp.is_success:
                logger.error("webhook_rotation_list_failed", extra={"status": resp.status_code, "body": resp.text[:300]})
                break
            data = resp.json()
            addresses.extend(data.get("data", []))
            url = (data.get("pagination") or {}).get("next")
        return {a.lower().strip() for a in addresses if a}

    async def _patch(self, to_add: list[str], to_remove: list[str]) -> None:
        """PATCH update-webhook-addresses in ≤500-addr batches."""
        if not self.auth_token or not self.webhook_id:
            raise RuntimeError("Missing Alchemy auth token or webhook id.")
        headers = {"X-Alchemy-Token": self.auth_token, "Content-Type": "application/json"}
        client = HttpClientManager.get_client("alchemy", timeout=30.0)
        # Pad so the loop runs once even when only one side has changes.
        total = max(len(to_add), len(to_remove), 1)
        for start in range(0, total, _BATCH):
            add_batch = to_add[start : start + _BATCH]
            remove_batch = to_remove[start : start + _BATCH]
            if not add_batch and not remove_batch:
                continue
            resp = await client.patch(
                f"{_BASE_URL}/update-webhook-addresses",
                headers=headers,
                json={
                    "webhook_id": self.webhook_id,
                    "addresses_to_add": add_batch,
                    "addresses_to_remove": remove_batch,
                },
            )
            if not resp.is_success:
                raise RuntimeError(f"Alchemy sync failed HTTP {resp.status_code}: {resp.text[:500]}")
            logger.info("webhook_rotation_patched", extra={"added": len(add_batch), "removed": len(remove_batch)})

    # -- Postgres selection ---------------------------------------------------

    async def select_top_candidates(
        self,
        session: AsyncSession,
        total_limit: int = 300,
        chain_quotas: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Top wallets with balanced per-chain quotas (default 180 ETH / 60 ARB / 60 BASE).

        Within each chain wallets are ranked by ``quality_score * velocity_penalty``
        so noisy/bot wallets sink, then clamped to that chain's seat count. The
        result set is bounded by ``total_limit`` overall.
        """
        quotas = chain_quotas or _CHAIN_QUOTAS
        result = await session.execute(
            _SELECT_TOP,
            {
                "eth_limit": quotas.get("ETH", 180),
                "arb_limit": quotas.get("ARB", 60),
                "base_limit": quotas.get("BASE", 60),
                "total_limit": total_limit,
            },
        )
        return [
            {
                "address": str(r["address"]).lower().strip(),
                "chain": str(r["chain"] or ""),
                "quality_score": float(r["quality_score"]),
                "category": str(r["category"] or ""),
            }
            for r in result.mappings().all()
        ]

    async def _reconcile_monitored(self, monitored: set[str]) -> None:
        async with self.session_factory() as session:
            from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository

            await CuratedWalletRepository(session).set_monitored_flags(monitored)
            await session.commit()

    # -- Orchestration --------------------------------------------------------

    async def sync_rotation_cycle(self, limit: int = 300) -> dict[str, int]:
        """Diff the selected 300 against Alchemy and apply the delta.

        Returns a summary: addresses added, removed, and now actively monitored.
        """
        async with self.session_factory() as session:
            candidates = await self.select_top_candidates(session, limit)
        candidate_addrs = {c["address"] for c in candidates}

        current = await self.get_currently_monitored_on_alchemy()
        to_add = sorted(candidate_addrs - current)
        to_remove = sorted(current - candidate_addrs)

        if to_add or to_remove:
            await self._patch(to_add, to_remove)
        else:
            logger.info("webhook_rotation_in_sync", extra={"monitored": len(candidate_addrs)})

        await self._reconcile_monitored(candidate_addrs)
        summary = {"added": len(to_add), "removed": len(to_remove), "monitored": len(candidate_addrs)}
        logger.info("webhook_rotation_cycle_done", extra=summary)
        return summary

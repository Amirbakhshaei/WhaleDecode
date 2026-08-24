"""Behavioral Profiling & Historical Intent Engine (Module 1, Hybrid A+B).

Option A core: a rolling 90-day ledger built from our own ``candidate_events``.
Win-rate = share of the wallet's past accumulations whose token is up >= 10%
since entry (entry price at event time, current price as the mark — ponytail
approximation; a proper 72h-window backtest needs stored price series).

Option B fallback: wallets with no self-observed history get a Zerion PnL
snapshot (free tier, background-only) so the LLM still has intent context.

Profiles are pre-computed rows — alert-time enrichment is one cached DB read,
zero LLM tool latency.
"""
import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

LEDGER_DAYS = 90
WIN_THRESHOLD = 0.10  # +10% marks a winning accumulation
MIN_SAMPLE_FOR_CONFIDENCE = 3


def _classify_strategy(events: list[dict[str, Any]]) -> str:
    types = [e["event_type"] for e in events]
    total = max(len(types), 1)
    if types.count("SWAP") / total >= 0.5:
        return "DEX Scalper"
    if types.count("APPROVE") / total >= 0.3:
        return "Yield Farmer"
    return "Spot Accumulator"


def _summarize(events: list[dict[str, Any]], limit: int = 3) -> str:
    lines: list[str] = []
    for e in events[-limit:]:
        lines.append(f"{e['event_type']} ${e['value_usd']:,.0f} {e['token']}")
    return "; ".join(lines)


def compute_profile_from_ledger(
    events: list[dict[str, Any]], prices_now: dict[str, float]
) -> dict[str, Any]:
    """Pure computation: candidate-event rows -> profile fields.

    ``events`` items need: event_type, token (contract), token_amount,
    entry_price_usd, timestamp_unix. ``prices_now`` maps contract -> current USD.
    """
    if not events:
        return {}
    first_buy_per_token: dict[str, dict[str, Any]] = {}
    for e in sorted(events, key=lambda x: x["timestamp_unix"]):
        token = e["token"].lower()
        if token and token not in first_buy_per_token and e["event_type"] in ("SWAP", "TRANSFER"):
            first_buy_per_token[token] = e

    wins = 0
    decided = 0
    pnl = 0.0
    for token, e in first_buy_per_token.items():
        entry = float(e.get("entry_price_usd") or 0.0)
        now_price = float(prices_now.get(token) or 0.0)
        amount = float(e.get("token_amount") or 0.0)
        if entry <= 0 or now_price <= 0:
            continue
        decided += 1
        ret = now_price / entry - 1.0
        if ret >= WIN_THRESHOLD:
            wins += 1
            pnl += amount * entry * ret
        elif ret < 0:
            pnl += amount * entry * ret

    # Holding-period proxy: median gap between repeat accumulations of the same
    # token (a scalper re-buys within hours; an accumulator within weeks).
    gaps_by_token: dict[str, list[float]] = defaultdict(list)
    seen: dict[str, float] = {}
    for e in sorted(events, key=lambda x: x["timestamp_unix"]):
        token = e["token"].lower()
        if not token or e["event_type"] != "SWAP":
            continue
        ts = e["timestamp_unix"]
        if token in seen:
            gaps_by_token[token].append(ts - seen[token])
        seen[token] = ts
    all_gaps = sorted(g for gaps in gaps_by_token.values() for g in gaps)

    return {
        "historical_win_rate_30d": round(wins / decided, 4) if decided else 0.0,
        "avg_holding_period_days": round(all_gaps[len(all_gaps) // 2] / 86400, 2) if all_gaps else 0.0,
        "primary_strategy": _classify_strategy(events),
        "total_pnl_usd": round(pnl, 2),
        "sample_size_30d": len(first_buy_per_token),
    }


class BehavioralProfiler:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        price_oracle: Any | None = None,
        zerion_client: Any | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._price_oracle = price_oracle
        self._zerion = zerion_client

    async def refresh_profile(self, chain: str, address: str) -> None:
        """Recompute one wallet's profile from its own ledger; upsert idempotently."""
        chain, address = chain.lower(), address.lower()
        async with self._uow_factory() as uow:
            wallet = await uow.curated_wallets.get_by_address_and_chain(address, chain)
            rows = (
                await uow.candidate_events.recent_for_wallet(
                    wallet.id, datetime.now(UTC) - timedelta(days=LEDGER_DAYS)
                )
                if wallet is not None and wallet.id is not None
                else []
            )
        events = [_row_to_ledger_entry(r) for r in rows]
        prices_now: dict[str, float] = {}
        if self._price_oracle is not None:
            tokens = {e["token"] for e in events if e["token"]}
            for token in tokens:
                prices_now[token] = await self._price_oracle.get_token_price_usd(token, chain)
        computed = compute_profile_from_ledger(events, prices_now)
        values = {
            "chain": chain,
            "address": address,
            **computed,
            "recent_actions_summary": _summarize(events),
            "source": "self_observed",
        }
        if not computed and self._zerion is not None:
            snapshot = await self._zerion.wallet_snapshot(chain, address)
            values.update(
                {
                    "total_pnl_usd": snapshot.get("pnl_usd", 0.0),
                    "primary_strategy": snapshot.get("label") or "Unknown",
                    "source": "zerion",
                }
            )
        async with self._uow_factory() as uow:
            await uow.wallet_profiles.upsert(values)
            await uow.commit()

    async def enrich(self, chain: str, address: str) -> dict[str, Any]:
        """Alert-time context: one cached read, no blocking third-party calls.

        Cold miss → instant baseline (win_rate 0.0, 0ms third-party latency)
        plus a fire-and-forget background task that backfills the profile from
        our own ledger + price oracle so the next event for this wallet is warm.
        """
        chain, address = chain.lower(), address.lower()
        async with self._uow_factory() as uow:
            profile = await uow.wallet_profiles.get(chain, address)
        if profile is None:
            asyncio.create_task(self._backfill(chain, address))
            return {
                "wallet_strategy": "Unknown",
                "wallet_win_rate_30d": 0.0,
                "wallet_intent_hint": "No tracked history yet; baseline confidence.",
                "wallet_profile_cold_start": True,
            }
        ctx: dict[str, Any] = {
            "wallet_strategy": profile.primary_strategy,
            "wallet_total_pnl_usd": profile.total_pnl_usd,
            "wallet_recent_actions": profile.recent_actions_summary,
        }
        if profile.sample_size_30d >= MIN_SAMPLE_FOR_CONFIDENCE:
            ctx["wallet_win_rate_30d"] = profile.historical_win_rate_30d
            ctx["wallet_avg_holding_period_days"] = profile.avg_holding_period_days
            ctx["wallet_intent_hint"] = (
                f"Historically profitable on {round(profile.historical_win_rate_30d * 100)}% "
                f"of tracked accumulations over the last 90 days."
            )
        return ctx

    async def _backfill(self, chain: str, address: str) -> None:
        """Background ledger rebuild — never blocks the alert pipeline."""
        try:
            await self.refresh_profile(chain, address)
        except Exception as exc:
            logger.warning(f"profile backfill failed for {address}: {exc}")


def _row_to_ledger_entry(row: Any) -> dict[str, Any]:
    """Flatten a CandidateEvent row into the pure-ledger shape."""
    raw: dict[str, Any] = row.raw_json if isinstance(row.raw_json, dict) else {}
    created = row.created_at.timestamp() if row.created_at else datetime.now(UTC).timestamp()
    return {
        "event_type": row.event_type,
        "token": str(raw.get("address") or ""),
        "token_amount": float(raw.get("token_amount") or 0.0),
        "entry_price_usd": float(raw.get("price_at_timestamp") or 0.0),
        "value_usd": float(raw.get("value_usd") or 0.0),
        "timestamp_unix": created,
    }

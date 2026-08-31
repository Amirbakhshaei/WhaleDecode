"""Pipeline telemetry & structured logging.

Centralized logging helpers for the data ingestion pipeline:
- Ingestion (poller/webhook): wallets polled, activities seen, filtered, inserted
- Investigation: events claimed, processed, skipped, completed
- Channel publishing: campaign actions, Telegram dispatch results
- Health: periodic pipeline heartbeat

All logs use structured JSON via structlog for easy querying (grep, Loki, Datadog, etc.).
"""
import asyncio
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import structlog

from whaledecode.config.settings import Settings

log = structlog.get_logger()

# Context var for request-scoped correlation IDs
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(cid: str) -> None:
    """Set correlation ID for current async context (e.g., webhook request, poller pass)."""
    _correlation_id.set(cid)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def _base_extra(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge correlation ID and timestamp into extra."""
    out = dict(extra or {})
    cid = get_correlation_id()
    if cid:
        out["correlation_id"] = cid
    out["ts"] = datetime.now(UTC).isoformat()
    return out


# ─── Ingestion Stage ────────────────────────────────────────────────────

def log_poll_start(chain: str, wallet_count: int) -> None:
    """Log poller pass start for a chain."""
    log.info(
        "pipeline_poll_start",
        extra=_base_extra({"chain": chain, "wallets_polled": wallet_count}),
    )


def log_activities_fetched(
    chain: str,
    wallet: str,
    activity_count: int,
    *,
    sample: list[dict] | None = None,
) -> None:
    """Log activities fetched for a wallet (with optional sample)."""
    extra = _base_extra(
        {
            "chain": chain,
            "wallet": wallet,
            "activities_fetched": activity_count,
        }
    )
    if sample:
        extra["sample"] = sample[:3]
    log.info("pipeline_activities_fetched", extra=extra)


def log_ingest_filtered(
    chain: str,
    wallet: str,
    tx_hash: str,
    reason: str,
    value_usd: float,
    floor: float,
) -> None:
    """Log an activity filtered out by the USD floor gate."""
    log.info(
        "pipeline_ingest_filtered",
        extra=_base_extra(
            {
                "chain": chain,
                "wallet": wallet,
                "tx_hash": tx_hash,
                "reason": reason,
                "value_usd": value_usd,
                "floor_usd": floor,
            }
        ),
    )


def log_ingest_inserted(
    chain: str,
    count: int,
    *,
    sample_dedupe_keys: list[str] | None = None,
) -> None:
    """Log successful candidate_events insertion."""
    extra = _base_extra(
        {
            "chain": chain,
            "events_inserted": count,
        }
    )
    if sample_dedupe_keys:
        extra["sample_dedupe_keys"] = sample_dedupe_keys[:5]
    log.info("pipeline_ingest_inserted", extra=extra)


def log_ingest_duplicate(
    chain: str,
    wallet: str,
    tx_hash: str,
    log_index: int,
) -> None:
    """Log a duplicate dedupe_key skipped by ON CONFLICT."""
    log.debug(
        "pipeline_ingest_duplicate",
        extra=_base_extra(
            {
                "chain": chain,
                "wallet": wallet,
                "tx_hash": tx_hash,
                "log_index": log_index,
            }
        ),
    )


# ─── Investigation Stage ────────────────────────────────────────────────

def log_investigation_claim(event_id: int, dedupe_key: str, tx_hash: str, chain: str) -> None:
    """Log event claimed for investigation."""
    log.info(
        "pipeline_investigation_claim",
        extra=_base_extra(
            {
                "event_id": event_id,
                "dedupe_key": dedupe_key,
                "tx_hash": tx_hash,
                "chain": chain,
            }
        ),
    )


def log_investigation_result(
    event_id: int,
    dedupe_key: str,
    status: str,
    *,
    score: float | None = None,
    value_usd: float | None = None,
    reason: str | None = None,
) -> None:
    """Log investigation outcome."""
    extra = _base_extra(
        {
            "event_id": event_id,
            "dedupe_key": dedupe_key,
            "status": status,
        }
    )
    if score is not None:
        extra["score"] = score
    if value_usd is not None:
        extra["value_usd"] = value_usd
    if reason:
        extra["reason"] = reason
    log.info("pipeline_investigation_result", extra=extra)


def log_investigation_skipped(
    event_id: int,
    dedupe_key: str,
    reason: str,
    *,
    score: float | None = None,
    value_usd: float | None = None,
) -> None:
    """Convenience: log investigation skip with reason."""
    log_investigation_result(
        event_id, dedupe_key, "skipped", score=score, value_usd=value_usd, reason=reason
    )


# ─── Channel Publishing Stage ──────────────────────────────────────────

def log_channel_gate_check(
    event_id: int,
    dedupe_key: str,
    score: int,
    value_usd: float,
    min_score: int,
    min_usd: float,
    passed: bool,
) -> None:
    """Log channel floor gate check (score/value thresholds)."""
    log.info(
        "pipeline_channel_gate",
        extra=_base_extra(
            {
                "event_id": event_id,
                "dedupe_key": dedupe_key,
                "score": score,
                "value_usd": value_usd,
                "min_score": min_score,
                "min_usd": min_usd,
                "passed": passed,
            }
        ),
    )


def log_channel_fatigue_cap(
    event_id: int,
    dedupe_key: str,
    hourly: int,
    daily: int,
    chain_daily: int,
    max_hourly: int,
    max_daily: int,
    max_chain_daily: int,
) -> None:
    """Log anti-fatigue cap hit."""
    log.info(
        "pipeline_channel_capped",
        extra=_base_extra(
            {
                "event_id": event_id,
                "dedupe_key": dedupe_key,
                "hourly_count": hourly,
                "daily_count": daily,
                "chain_daily_count": chain_daily,
                "max_hourly": max_hourly,
                "max_daily": max_daily,
                "max_chain_daily": max_chain_daily,
            }
        ),
    )


def log_channel_synthesis_validation(
    event_id: int,
    dedupe_key: str,
    valid: bool,
    fallback_detected: bool = False,
) -> None:
    """Log synthesis quality gate."""
    log.info(
        "pipeline_channel_synthesis",
        extra=_base_extra(
            {
                "event_id": event_id,
                "dedupe_key": dedupe_key,
                "valid": valid,
                "fallback_detected": fallback_detected,
            }
        ),
    )


def log_channel_dispatch(
    event_id: int,
    dedupe_key: str,
    campaign_id: int | None,
    action: str,
    message_id: int | None,
    success: bool,
    error: str | None = None,
) -> None:
    """Log Telegram dispatch outcome."""
    level = log.info if success else log.error
    extra = _base_extra(
        {
            "event_id": event_id,
            "dedupe_key": dedupe_key,
            "campaign_id": campaign_id,
            "action": action,
            "message_id": message_id,
            "success": success,
        }
    )
    if error:
        extra["error"] = error
    level("pipeline_channel_dispatch", extra=extra)


# ─── Health / Heartbeat ────────────────────────────────────────────────

async def periodic_heartbeat(
    settings: Settings,
    session_factory,
    interval_seconds: int = 60,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Emit periodic pipeline health metrics.

    Logs: pending queue depth, recent throughput, worker status, channel config.
    """
    from whaledecode.adapters.db.uow import UnitOfWork

    while not (stop_event and stop_event.is_set()):
        try:
            async with UnitOfWork(session_factory) as uow:
                pending = await uow.candidate_events.list_by_status("pending", limit=1)
                pending_count = len(pending)
                completed_today = await uow.candidate_events.count_published_since(
                    datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                )
            log.info(
                "pipeline_heartbeat",
                extra=_base_extra(
                    {
                        "pending_queue": pending_count,
                        "completed_today": completed_today,
                        "channel_configured": bool(
                            settings.CHANNEL_CHAT_ID or settings.TELEGRAM_CHANNEL_ID
                        ),
                        "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
                    }
                ),
            )
        except Exception as e:
            log.error("pipeline_heartbeat_failed", extra=_base_extra({"error": str(e)}))
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break


# ─── Decorator for auto-correlation ────────────────────────────────────

def with_correlation(correlation_id: str | None = None):
    """Context manager / decorator to set correlation ID for a block."""

    class _Ctx:
        def __init__(self, cid: str | None):
            self.cid = cid or f"corr-{datetime.now(UTC).timestamp()}"

        def __enter__(self):
            self.token = _correlation_id.set(self.cid)
            return self.cid

        def __exit__(self, *exc):
            _correlation_id.reset(self.token)

        async def __aenter__(self):
            return self.__enter__()

        async def __aexit__(self, *exc):
            return self.__exit__(*exc)

    return _Ctx(correlation_id)
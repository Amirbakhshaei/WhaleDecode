"""Consumer: background AI worker.

Claims ``pending`` candidate_events with atomic row locks, runs
``InvestigationService``, and dispatches the Glass Whale briefing to Telegram.
Decoupled from the fetcher: it only reads the database and talks to Telegram.
"""
import asyncio
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import LinkPreviewOptions
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.telegram.formatters.channel_formatter import (
    is_valid_synthesis,
    parse_synthesis_points,
)
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.config.alert_policy import GLOBAL_POLICY, policy_for
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.admin_audit_log import AdminAuditLog
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.infrastructure.telemetry import capture_exception

log = structlog.get_logger()

MAX_ATTEMPTS = 3

# Un-bypassable Telegram channel floor: low-score or low-value alerts never go out.
CHANNEL_MIN_SCORE = 50
CHANNEL_MIN_VALUE_USD = 50_000.0


class BackgroundAIWorker:
    """Continually claims pending candidate_events, investigates, and dispatches alerts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        investigation_service: InvestigationService,
        settings: Settings,
        bot: Bot | None = None,
        channel_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._investigation = investigation_service
        self._settings = settings
        self._bot = bot
        self._channel_id = channel_id or settings.CHANNEL_CHAT_ID or settings.TELEGRAM_CHANNEL_ID or ""

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Reap stale claims from a previously crashed run, then poll forever.

        Never crashes silently; backs off with a sleep on failure.
        """
        try:
            async with UnitOfWork(self._session_factory) as uow:
                reaped = await uow.candidate_events.reap_zombie_events()
                await uow.commit()
        except Exception as e:
            log.error("worker_reap_failed", extra={"error": str(e)}, exc_info=True)
        else:
            (log.warning if reaped else log.info)("worker_reaped_zombie_events", extra={"count": reaped})

        while not (stop_event and stop_event.is_set()):
            try:
                await self.process_pending()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[PIPELINE_ERROR] Stage 'worker_loop' failed: {e}", exc_info=True)
                capture_exception(e)
            try:
                await asyncio.sleep(self._settings.POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise

    async def process_pending(self) -> None:
        """Claim one pending event (atomic lock), investigate, dispatch, update status.

        On failure the event is returned to ``pending`` so another pass retries it.
        Events the investigation skips (below gate threshold) are marked ``skipped``,
        a terminal state — never re-claimed, never dispatched.
        """
        async with UnitOfWork(self._session_factory) as uow:
            claimed = await uow.candidate_events.claim_next_pending(limit=1)
            if not claimed:
                return
            event = claimed[0]
            assert event.id is not None, "claimed candidate event must have an id"
            await uow.candidate_events.set_status(event.id, "processing")
            await uow.commit()

        try:
            result = await self._investigation.process_event(event)
            if result.get("status") == "skipped":
                async with UnitOfWork(self._session_factory) as uow:
                    await uow.candidate_events.set_status(event.id, "skipped")
                    await uow.commit()
                log.info(
                    "worker_event_skipped",
                    extra={
                        "dedupe_key": event.dedupe_key,
                        "status": "skipped",
                        "reason": result.get("reason", "unknown"),
                        "tx": str(event.tx_hash),
                    },
                )
                return

            score, value_usd = self._channel_metrics(event, result)
            policy = policy_for(event.chain)
            min_score = policy.min_score_to_publish if policy else CHANNEL_MIN_SCORE
            min_usd = policy.min_usd_threshold if policy else CHANNEL_MIN_VALUE_USD
            if score < min_score or value_usd < min_usd:
                async with UnitOfWork(self._session_factory) as uow:
                    await uow.candidate_events.set_status(event.id, "skipped")
                    await uow.commit()
                log.info(
                    "worker_event_below_channel_floor",
                    extra={
                        "dedupe_key": event.dedupe_key,
                        "reason": "Below channel publish floor (score/value)",
                        "score": score,
                        "value_usd": value_usd,
                        "min_score": min_score,
                        "min_usd": min_usd,
                        "tx": str(event.tx_hash),
                    },
                )
                return

            # Anti-fatigue caps; $2M+ moves (black swans) bypass all caps.
            chain_daily_cap = policy.max_daily_alerts if policy else GLOBAL_POLICY.max_alerts_per_day
            now = datetime.now(UTC)
            async with UnitOfWork(self._session_factory) as uow:
                hourly = await uow.candidate_events.count_published_since(now - timedelta(hours=1))
                daily = await uow.candidate_events.count_published_since(now - timedelta(days=1))
                chain_daily = await uow.candidate_events.count_published_since(
                    now - timedelta(days=1), chain=event.chain
                )
                capped = value_usd < GLOBAL_POLICY.black_swan_usd_override and (
                    hourly >= GLOBAL_POLICY.max_alerts_per_hour
                    or daily >= GLOBAL_POLICY.max_alerts_per_day
                    or chain_daily >= chain_daily_cap
                )
                if capped:
                    await uow.candidate_events.set_status(event.id, "skipped")
                    await uow.commit()
                    log.info(
                        "worker_event_capped",
                        extra={
                            "dedupe_key": event.dedupe_key,
                            "reason": "Anti-fatigue alert cap reached",
                            "hourly": hourly,
                            "daily": daily,
                            "chain_daily": chain_daily,
                            "tx": str(event.tx_hash),
                        },
                    )
                    return

            # Pre-publish gatekeeper: never broadcast placeholder/fallback synthesis.
            synthesis = parse_synthesis_points(result)
            if not is_valid_synthesis(
                " ".join([synthesis["profile"], synthesis["context"], synthesis["impact"]])
            ):
                async with UnitOfWork(self._session_factory) as uow:
                    await uow.candidate_events.set_status(event.id, "skipped")
                    await uow.commit()
                log.info(
                    "worker_event_synthesis_invalid",
                    extra={
                        "dedupe_key": event.dedupe_key,
                        "reason": "Synthesis contains fallback/placeholder text",
                        "tx": str(event.tx_hash),
                    },
                )
                log.info(
                    f"[DISPATCH_SKIP] Event ID={event.id} suppressed: synthesis failed validation "
                    f"(fallback/placeholder). Tx={event.tx_hash}"
                )
                return

            dispatched = await self._dispatch(event, result)
            async with UnitOfWork(self._session_factory) as uow:
                await uow.candidate_events.set_status(event.id, "completed")
                if dispatched:
                    await uow.candidate_events.mark_published(event.id)
                await uow.commit()
            log.info("worker_event_done", extra={"dedupe_key": event.dedupe_key, "status": "completed"})
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter):
            log.warning("Telegram API unreachable, deferring alert.", extra={"dedupe_key": event.dedupe_key})
            async with UnitOfWork(self._session_factory) as uow:
                await uow.candidate_events.set_status(event.id, "pending")
                await uow.commit()
        except Exception as e:
            log.error(f"[PIPELINE_ERROR] Stage 'process_pending' failed for tx {event.tx_hash}: {e}", exc_info=True)
            capture_exception(e)
            async with UnitOfWork(self._session_factory) as uow:
                next_status = await uow.candidate_events.record_failure(event.id, max_attempts=MAX_ATTEMPTS)
                if next_status == "dead_letter":
                    await uow.admin_audit_logs.create(self._dead_letter_audit(event, e))
                await uow.commit()
            if next_status == "dead_letter":
                log.warning("worker_event_dead_lettered", extra={"dedupe_key": event.dedupe_key})

    @staticmethod
    def _dead_letter_audit(event: CandidateEvent, exc: Exception) -> AdminAuditLog:
        """Capture the toxic event payload and exception trace for forensics."""
        return AdminAuditLog(
            admin_id=0,
            action="candidate_event_dead_lettered",
            target_type="candidate_event",
            target_id=event.id,
            diff_json={
                "dedupe_key": event.dedupe_key,
                "tx_hash": str(event.tx_hash),
                "chain": event.chain,
                "event_type": event.event_type,
                "raw_json": event.raw_json,
                "attempt_count": event.attempt_count,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(),
            },
        )

    @staticmethod
    def _channel_metrics(event: CandidateEvent, result: dict[str, Any]) -> tuple[int, float]:
        """The exact Score (0-100) and USD value shown on the channel post."""
        score = int(float(result.get("risk_score", 0.0)) * 100)
        raw = event.raw_json if isinstance(event.raw_json, dict) else {}
        value = float(raw.get("value_usd", 0) or 0.0)
        return score, value

    async def _dispatch(self, event: CandidateEvent, result: dict[str, Any]) -> bool:
        """Send the alert; return True only if a message was actually dispatched.

        Campaign-aware: the first event in a wallet's 30-minute window publishes
        the rich Glass Whale briefing (CREATED); subsequent in-window events edit
        that message in place (MUTATED); events past the window or crossing $2M
        publish an anchored reply (THREADED).
        """
        if not self._bot or not self._channel_id:
            log.info("worker_dispatch_skipped", extra={"channel_id": self._channel_id or "NOT_SET"})
            return False
        summary = result.get("summary", "")
        if not summary:
            log.warning("worker_dispatch_empty_summary", extra={"dedupe_key": event.dedupe_key})
            return False

        from whaledecode.adapters.telegram.dispatcher import safe_telegram_send
        from whaledecode.adapters.telegram.formatters.campaign_formatter import (
            format_mutated_campaign_alert,
            format_threaded_campaign_alert,
        )
        from whaledecode.adapters.telegram.formatters.channel_formatter import (
            build_alert_data,
            format_alert,
        )
        from whaledecode.adapters.telegram.keyboards import get_channel_alert_keyboard
        from whaledecode.application.services.campaign_service import CampaignService

        # Resolve + publish inside one transaction: if Telegram is unreachable the
        # exception propagates and the UoW rolls back, so a failed CREATED never
        # leaves an orphan campaign that breaks the MUTATED path on retry.
        async with UnitOfWork(self._session_factory) as uow:
            campaign, action = await CampaignService.resolve_event_campaign(
                uow.session, event
            )

            if action == "CREATED":
                msg = format_alert(
                    build_alert_data(
                        event.model_dump(),
                        result,
                        bot_username=self._settings.BOT_USERNAME,
                    )
                )
                sent = await safe_telegram_send(
                    self._bot,
                    self._channel_id,
                    msg,
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_channel_alert_keyboard(
                        str(event.chain),
                        str(event.tx_hash),
                        str((event.raw_json or {}).get("from", "")) if isinstance(event.raw_json, dict) else "",
                        self._settings.BOT_USERNAME,
                    ),
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                msg_id = getattr(sent, "message_id", sent)
                if msg_id:
                    await uow.campaigns.set_telegram_message_id(campaign.id, msg_id)
                await uow.candidate_events.update(event)
                await uow.commit()
                log.info("worker_dispatched_campaign_created", extra={"dedupe_key": event.dedupe_key, "campaign_id": campaign.id})
                log.info(f"[TELEGRAM_DISPATCH] ✅ Broadcasted Event ID={event.id} to Telegram! Campaign={campaign.id} MsgID={msg_id}")
                return True

            if action == "MUTATED":
                if not campaign.telegram_message_id:
                    log.warning("worker_campaign_no_message_id", extra={"campaign_id": campaign.id})
                    return False
                await self._bot.edit_message_text(
                    chat_id=self._channel_id,
                    message_id=campaign.telegram_message_id,
                    text=format_mutated_campaign_alert(campaign),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                await uow.candidate_events.update(event)
                await uow.commit()
                log.info("worker_dispatched_campaign_mutated", extra={"dedupe_key": event.dedupe_key, "campaign_id": campaign.id})
                log.info(f"[TELEGRAM_DISPATCH] ✅ Broadcasted Event ID={event.id} to Telegram! Campaign={campaign.id} MsgID={campaign.telegram_message_id}")
                return True

            # THREADED
            sent = await safe_telegram_send(
                self._bot,
                self._channel_id,
                format_threaded_campaign_alert(event, campaign),
                reply_to_message_id=campaign.telegram_message_id,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            new_msg_id = getattr(sent, "message_id", sent)
            if new_msg_id:
                await uow.campaigns.set_telegram_message_id(campaign.id, new_msg_id)
            await uow.candidate_events.update(event)
            await uow.commit()
            log.info("worker_dispatched_campaign_threaded", extra={"dedupe_key": event.dedupe_key, "campaign_id": campaign.id})
            log.info(f"[TELEGRAM_DISPATCH] ✅ Broadcasted Event ID={event.id} to Telegram! Campaign={campaign.id} MsgID={new_msg_id}")
            return True

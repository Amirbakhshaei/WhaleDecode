"""Consumer: background AI worker.

Claims ``pending`` candidate_events with atomic row locks, runs
``InvestigationService``, and dispatches the Glass Whale briefing to Telegram.
Decoupled from the fetcher: it only reads the database and talks to Telegram.
"""
import asyncio
import re
from typing import Any

import structlog
import telegramify_markdown
from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent

log = structlog.get_logger()

_SPOILER_CODE_RE = re.compile(r"\|\|`([^`\n]+)`\|\|")


def normalize_spoilers(text: str) -> str:
    """telegramify-markdown drops ``||spoiler||`` when it wraps an inline code
    span; unwrap the code first so the spoiler entity is emitted."""
    return _SPOILER_CODE_RE.sub(r"||\1||", text)


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
        """Main loop: never crashes silently, backs off with a sleep on failure."""
        while not (stop_event and stop_event.is_set()):
            try:
                await self.process_pending()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("worker_loop_error", error=str(e), exc_info=True)
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
                log.info("worker_event_skipped", dedupe_key=event.dedupe_key, status="skipped")
                return
            dispatched = await self._dispatch(event, result)
            async with UnitOfWork(self._session_factory) as uow:
                await uow.candidate_events.set_status(event.id, "completed")
                if dispatched:
                    await uow.candidate_events.mark_published(event.id)
                await uow.commit()
            log.info("worker_event_done", dedupe_key=event.dedupe_key, status="completed")
        except Exception as e:
            log.error("worker_event_failed", dedupe_key=event.dedupe_key, error=str(e), exc_info=True)
            async with UnitOfWork(self._session_factory) as uow:
                await uow.candidate_events.set_status(event.id, "pending")
                await uow.commit()

    async def _dispatch(self, event: CandidateEvent, result: dict[str, Any]) -> bool:
        """Send the alert; return True only if a message was actually dispatched."""
        if not self._bot or not self._channel_id:
            log.info("worker_dispatch_skipped", channel_id=self._channel_id or "NOT_SET")
            return False
        summary = result.get("summary", "")
        if not summary:
            log.warning("worker_dispatch_empty_summary", dedupe_key=event.dedupe_key)
            return False

        from whaledecode.adapters.telegram.keyboards import build_keyboard

        text, entities = telegramify_markdown.convert(normalize_spoilers(summary))
        await self._bot.send_message(
            chat_id=self._channel_id,
            text=text,
            entities=[e.to_dict() for e in entities],
            parse_mode=None,
            reply_markup=build_keyboard(str(event.tx_hash)),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        log.info("worker_dispatched", dedupe_key=event.dedupe_key)
        return True

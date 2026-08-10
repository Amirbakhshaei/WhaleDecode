import asyncio
from typing import Any

import pytest
from pydantic import SecretStr
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.worker import MAX_ATTEMPTS, BackgroundAIWorker
from whaledecode.config.settings import Settings

GLASS_WHALE_SUMMARY = (
    "🫧 **Whale Accumulation**\n"
    "💎 **Value:** `$150,000` PEPE\n"
    "🌐 **Chain:** Ethereum\n"
    "🎯 **Risk:** 85%\n\n"
    "> **🧠 SMC Intelligence**\n"
    "> Funds consolidated into a fresh address, hinting at accumulation.\n\n"
    "**Trace Metrics**\n"
    "Tx: ||`0xabc123`||\n"
    "From: ||`0xdeadbeef`||\n"
    "To: ||`0xbeefcafe`||"
)


def _settings(**overrides: Any) -> Settings:
    base = {
        "BOT_TOKEN": SecretStr("test"),
        "GROQ_API_KEY": SecretStr("test"),
        "POLL_INTERVAL_SECONDS": 0,
    }
    base.update(overrides)
    return Settings(**base)


class FakeInvestigation:
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def process_event(self, event) -> dict:
        if self._error:
            raise self._error
        return self._result or {"summary": GLASS_WHALE_SUMMARY, "risk_score": 0.8}


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self._error = error

    async def send_message(self, **kwargs: Any) -> None:
        if self._error:
            raise self._error
        self.sent.append(kwargs)


def _pending_data(dedupe_key: str) -> dict:
    return {
        "wallet_id": 1,
        "chain": "ETH",
        "tx_hash": "0x" + "c" * 64,
        "log_index": 0,
        "block_number": 100,
        "event_type": "TRANSFER",
        "raw_json": {"value_usd": 100.0},
        "score": 80.0,
        "dedupe_key": dedupe_key,
    }


async def _seed_pending(session_factory, dedupe_key: str = "worker:1") -> None:
    async with UnitOfWork(session_factory) as uow:
        await uow.candidate_events.create_pending(_pending_data(dedupe_key))
        await uow.commit()


@pytest.mark.asyncio
async def test_process_pending_investigates_dispatches_and_completes(session_factory) -> None:
    await _seed_pending(session_factory)
    bot = FakeBot()
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(),
        _settings(),
        bot=bot,
        channel_id="-100channel",
    )

    await worker.process_pending()

    assert len(bot.sent) == 1
    msg = bot.sent[0]
    assert "WHALE ALERT" in msg["text"]
    assert "TRADER INTELLIGENCE" in msg["text"]
    assert "0x" in msg["text"]
    assert "||" not in msg["text"]
    assert msg["chat_id"] == "-100channel"
    assert msg["parse_mode"] == "HTML"
    assert msg["reply_markup"] is not None

    async with UnitOfWork(session_factory) as uow:
        events = await uow.candidate_events.claim_next_pending(limit=10)
        claimed = await uow.candidate_events.get(1)
    assert events == []
    assert claimed is not None
    assert claimed.status == "completed"
    assert claimed.published_at is not None


@pytest.mark.asyncio
async def test_process_pending_noop_when_nothing_pending(session_factory) -> None:
    bot = FakeBot()
    worker = BackgroundAIWorker(session_factory, FakeInvestigation(), _settings(), bot=bot, channel_id="-100")

    await worker.process_pending()

    assert bot.sent == []


@pytest.mark.asyncio
async def test_process_pending_reverts_to_pending_on_failure(session_factory) -> None:
    await _seed_pending(session_factory, "worker:fail")
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(error=RuntimeError("llm down")),
        _settings(),
        bot=FakeBot(),
        channel_id="-100",
    )

    await worker.process_pending()

    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "pending"
    assert claimed.attempt_count == 1


@pytest.mark.asyncio
async def test_process_pending_dead_letters_after_max_attempts(session_factory) -> None:
    await _seed_pending(session_factory, "worker:dlq")
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(error=RuntimeError("llm down")),
        _settings(),
        bot=FakeBot(),
        channel_id="-100",
    )

    await worker.process_pending()
    await worker.process_pending()

    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "pending"
    assert claimed.attempt_count == 2

    await worker.process_pending()

    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "dead_letter"
    assert claimed.attempt_count == 3


@pytest.mark.asyncio
async def test_process_pending_dead_letter_writes_audit_log(session_factory) -> None:
    import json

    from sqlalchemy import select
    from whaledecode.adapters.db.models.admin_audit_log import AdminAuditLogModel

    await _seed_pending(session_factory, "worker:dlqaudit")
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(error=RuntimeError("llm down")),
        _settings(),
        bot=FakeBot(),
        channel_id="-100",
    )

    for _ in range(3):
        await worker.process_pending()

    async with session_factory() as session:
        logs = (await session.execute(select(AdminAuditLogModel))).scalars().all()
    assert len(logs) == 1
    audit = logs[0]
    assert audit.action == "candidate_event_dead_lettered"
    assert audit.target_type == "candidate_event"
    assert audit.target_id == 1
    diff = json.loads(audit.diff_json)
    assert diff["dedupe_key"] == "worker:dlqaudit"
    assert "RuntimeError: llm down" in diff["error"]
    assert "Traceback" in diff["trace"]


@pytest.mark.asyncio
async def test_run_reaps_zombie_events_once_at_startup(session_factory) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update
    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel

    await _seed_pending(session_factory, "worker:zombie")
    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.claim_next_pending()
        await uow.candidate_events.set_status(claimed[0].id, "processing")
        await uow.commit()

    async with session_factory() as session:
        await session.execute(
            update(CandidateEventModel)
            .where(CandidateEventModel.id == 1)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=15))
        )
        await session.commit()

    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(error=RuntimeError("llm down")),
        _settings(),
        bot=FakeBot(),
        channel_id="-100",
    )

    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(0.05)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status != "processing"


@pytest.mark.asyncio
async def test_process_pending_skipped_does_not_dispatch(session_factory) -> None:
    await _seed_pending(session_factory, "worker:skip")
    bot = FakeBot()
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(result={"status": "skipped", "reason": "Below gate threshold"}),
        _settings(),
        bot=bot,
        channel_id="-100",
    )

    await worker.process_pending()

    assert bot.sent == []
    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "skipped"
    assert claimed.published_at is None


@pytest.mark.asyncio
async def test_process_pending_empty_summary_completed_not_published(session_factory) -> None:
    await _seed_pending(session_factory, "worker:emptysum")
    bot = FakeBot()
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(result={"summary": "", "risk_score": 0.8}),
        _settings(),
        bot=bot,
        channel_id="-100",
    )

    await worker.process_pending()

    assert bot.sent == []
    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "completed"
    assert claimed.published_at is None


@pytest.mark.asyncio
async def test_run_survives_errors_and_stops(session_factory) -> None:
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(error=RuntimeError("boom")),
        _settings(),
        bot=FakeBot(),
        channel_id="-100",
    )

    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(0.05)
    assert not task.done()

    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert task.done()


@pytest.mark.asyncio
async def test_network_error_defers_alert_keeps_pending_no_attempt(session_factory) -> None:
    """A transient Telegram outage must not burn a dead-letter attempt while the
    network is down; the event stays pending and is retried next pass."""
    from aiogram.exceptions import TelegramNetworkError

    await _seed_pending(session_factory, "worker:network")
    bot = FakeBot(error=TelegramNetworkError(method="sendMessage", message="502 Bad Gateway"))
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(),
        _settings(),
        bot=bot,
        channel_id="-100",
    )

    await worker.process_pending()

    assert bot.sent == []
    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "pending"
    assert claimed.attempt_count == 0
    assert claimed.published_at is None


@pytest.mark.asyncio
async def test_network_error_never_dead_letters_after_many_attempts(session_factory) -> None:
    """Even repeated outages leave the event pending and retryable, never dead-lettered."""
    from aiogram.exceptions import TelegramServerError

    await _seed_pending(session_factory, "worker:network2")
    bot = FakeBot(error=TelegramServerError(method="sendMessage", message="503 Service Unavailable"))
    worker = BackgroundAIWorker(
        session_factory,
        FakeInvestigation(),
        _settings(),
        bot=bot,
        channel_id="-100",
    )

    for _ in range(MAX_ATTEMPTS * 2):
        await worker.process_pending()

    async with UnitOfWork(session_factory) as uow:
        claimed = await uow.candidate_events.get(1)
    assert claimed is not None
    assert claimed.status == "pending"
    assert claimed.attempt_count == 0
    assert claimed.published_at is None

    async with UnitOfWork(session_factory) as uow:
        claimable = await uow.candidate_events.claim_next_pending(limit=1)
    assert len(claimable) == 1

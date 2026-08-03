import asyncio
from typing import Any

import pytest
from pydantic import SecretStr
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.worker import BackgroundAIWorker, normalize_spoilers
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
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs: Any) -> None:
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


def test_normalize_spoilers_unwraps_nested_code() -> None:
    out = normalize_spoilers("Tx: ||`0xabc`||")
    assert out == "Tx: ||0xabc||"


def test_normalize_spoilers_keeps_plain_spoilers() -> None:
    out = normalize_spoilers("Tx: ||0xabc||")
    assert out == "Tx: ||0xabc||"


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
    assert "0xabc123" in msg["text"]
    assert "||" not in msg["text"]
    assert msg["chat_id"] == "-100channel"
    assert any(e.get("type") == "spoiler" for e in msg["entities"])
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

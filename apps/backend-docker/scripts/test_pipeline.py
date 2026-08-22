"""
Synthetic pipeline test: mock event -> ORION graph -> DB -> Telegram channel.

Usage:
    python scripts/test_pipeline.py          # full pipeline
    python scripts/test_pipeline.py --dry    # skip Telegram publish
"""
from __future__ import annotations

import asyncio
import sys
import time

import structlog

from whaledecode.adapters.db.session import create_session_factory
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm.factory import LLMFactory
from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
from whaledecode.adapters.telegram.formatters.channel_formatter import (
    format_premium_event_post,
)
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.agent_run import AgentRun
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.value_objects.hash import Hash

log = structlog.get_logger()

MOCK_TX_HASH = "0x" + "ab" * 32
MOCK_EVENT = CandidateEvent(
    wallet_id=9,
    chain="ethereum",
    tx_hash=Hash(MOCK_TX_HASH),
    log_index=0,
    block_number=22_000_000,
    event_type="TRANSFER",
    raw_json={
        "token": "PEPE",
        "amount": "500000000",
        "from": "0x" + "00" * 20,
        "to": "0x" + "ff" * 20,
        "value_usd": 4250.0,
    },
    score=0.85,
    dedupe_key=f"test_pipeline_{int(time.time())}",
    status="NEW",
)


async def main() -> None:
    dry_run = "--dry" in sys.argv

    settings = Settings()
    settings.inject_langsmith_env()

    channel_id = settings.TELEGRAM_CHANNEL_ID or settings.CHANNEL_CHAT_ID
    log.info(
        "pipeline_start",
        dry_run=dry_run,
        channel_id=channel_id or "NOT_SET",
        channel_publish_enabled=settings.CHANNEL_PUBLISH_ENABLED,
    )

    # ── 1. Create mock event ─────────────────────────────────────────────
    event_dict = MOCK_EVENT.model_dump()
    log.info(
        "mock_event_created",
        chain=MOCK_EVENT.chain,
        event_type=MOCK_EVENT.event_type,
        token=MOCK_EVENT.raw_json["token"],
        amount=MOCK_EVENT.raw_json["amount"],
    )

    # ── 2. Run ORION graph ───────────────────────────────────────────────
    llm_factory = LLMFactory(settings)
    reasoner = LangGraphReasoner(settings, llm_factory)

    log.info("graph_execution_start")
    t0 = time.monotonic()
    result = await reasoner.investigate_event(event_dict)
    latency = int((time.monotonic() - t0) * 1000)
    log.info(
        "graph_execution_complete",
        latency_ms=latency,
        risk_score=result.get("risk_score"),
        summary_preview=result.get("summary", "")[:120],
    )

    # ── 3. Save to DB ────────────────────────────────────────────────────
    session_factory = create_session_factory(settings)
    async with UnitOfWork(session_factory) as uow:
        saved_event = await uow.candidate_events.create(MOCK_EVENT)
        log.info("db_event_saved", event_id=saved_event.id)

        run = AgentRun(
            trigger_type="event",
            trigger_ref_id=saved_event.id,
            graph_name="event_investigation",
            status="completed",
            input_json=event_dict,
            output_json=result,
            latency_ms=result.get("latency_ms", 0),
        )
        saved_run = await uow.agent_runs.create(run)

        saved_run.output_json = result
        await uow.agent_runs.update(saved_run)

        await uow.commit()
        log.info("db_save_success", run_id=saved_run.id, event_id=saved_event.id)

    # ── 4. Publish to Telegram ───────────────────────────────────────────
    msg = format_premium_event_post(event_dict, result)

    if dry_run or not settings.CHANNEL_PUBLISH_ENABLED or not channel_id:
        reason = "dry_run" if dry_run else "channel_not_configured"
        log.info("telegram_publish_skipped", reason=reason, channel_id=channel_id)
        log.info("channel_post_preview", message=msg)
        return

    print(f"\n⚠️  About to publish to channel: {channel_id}")
    print("    Press Ctrl+C within 3 seconds to abort...\n")
    await asyncio.sleep(3)

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(chat_id=channel_id, text=msg)

        async with UnitOfWork(session_factory) as uow:
            await uow.candidate_events.mark_published(saved_event.id)
            await uow.commit()

        log.info("telegram_publish_success", channel_id=channel_id, event_id=saved_event.id)
    except Exception as e:
        log.error("telegram_publish_failed", error=str(e))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

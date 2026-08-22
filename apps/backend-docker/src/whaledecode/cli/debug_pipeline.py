"""CLI diagnostic tool for tracing the candidate → investigation → channel pipeline.

Reads live DB state and replays the pipeline steps for one event entirely in
memory — no rows are written, no Telegram messages are sent, no prices are paid.

Run:
    python -m src.whaledecode.cli.debug_pipeline                # status report
    python -m src.whaledecode.cli.debug_pipeline --dry-run      # in-memory pipeline trace
    python -m src.whaledecode.cli.debug_pipeline --dry-run --event-id 42

Also wired as `whaledecode debug-pipeline`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.db.models.agent_run import AgentRunModel
from whaledecode.adapters.db.models.alert import AlertModel
from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.services.event_gate import (
    MIN_WHALE_THRESHOLD_USD,
    process_and_gate_candidate,
)

PENDING = "pending"


def _settings() -> Settings:
    settings = Settings()
    settings.inject_langsmith_env()
    return settings


def _factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    from whaledecode.adapters.db.session import create_session_factory

    return create_session_factory(settings)


def _row_to_event(model: CandidateEventModel) -> CandidateEvent:
    from whaledecode.domain.value_objects.hash import Hash

    return CandidateEvent(
        id=model.id,
        wallet_id=model.wallet_id,
        chain=model.chain,
        tx_hash=Hash(model.tx_hash),
        log_index=model.log_index,
        block_number=model.block_number,
        event_type=model.event_type,
        raw_json=json.loads(model.raw_json) if isinstance(model.raw_json, str) else {},
        score=model.score,
        dedupe_key=model.dedupe_key,
        status=model.status,
        attempt_count=model.attempt_count,
        published_at=model.published_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ---------------------------------------------------------------- report ----
async def _report(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        ce = select(CandidateEventModel.status, func.count()).group_by(CandidateEventModel.status)
        ce_rows = (await session.execute(ce)).all()
        al = select(AlertModel.status, func.count()).group_by(AlertModel.status)
        al_rows = (await session.execute(al)).all()

        recent = await session.execute(
            select(CandidateEventModel)
            .order_by(CandidateEventModel.created_at.desc())
            .limit(10)
        )

        runs = await session.execute(
            select(AgentRunModel)
            .where(AgentRunModel.trigger_type == "event")
            .order_by(AgentRunModel.id.desc())
            .limit(5)
        )

    print("=== candidate_events by status ===")
    for status, count in ce_rows:
        print(f"  {status:<12} {count}")
    print("\n=== alerts by status ===")
    for status, count in al_rows:
        print(f"  {status:<12} {count}")

    print("\n=== 10 most recent candidate events ===")
    for m in recent.scalars():
        raw = json.loads(m.raw_json) if isinstance(m.raw_json, str) else {}
        value = raw.get("value_usd", "?")
        print(
            f"  #{m.id:<5} {m.chain:<10} {m.event_type:<30} "
            f"value=${value if isinstance(value, float) else value}  "
            f"score={m.score}  status={m.status}"
        )

    print("\n=== 5 most recent event agent_runs ===")
    for r in runs.scalars():
        print(
            f"  #{r.id:<5} trigger={r.trigger_ref_id}  status={r.status}  "
            f"latency={r.latency_ms}ms  "
            f"error={(r.error or '')[:120]}"
        )


# --------------------------------------------------------------- dry run ----
async def _pick_event(
    factory: async_sessionmaker[AsyncSession], event_id: int | None
) -> CandidateEvent:
    async with factory() as session:
        if event_id is not None:
            row = await session.get(CandidateEventModel, event_id)
            if row is None:
                raise SystemExit(f"event_id {event_id} not found in candidate_events")
            return _row_to_event(row)
        pending = await session.execute(
            select(CandidateEventModel)
            .where(CandidateEventModel.status == PENDING)
            .order_by(CandidateEventModel.created_at.asc())
            .limit(1)
        )
        row = pending.scalar_one_or_none()
        if row is not None:
            return _row_to_event(row)
        fallback = await session.execute(
            select(CandidateEventModel)
            .order_by(CandidateEventModel.created_at.desc())
            .limit(1)
        )
        row = fallback.scalar_one_or_none()
        if row is None:
            raise SystemExit("no candidate events in database")
        return _row_to_event(row)


def _banner(title: str) -> None:
    print(f"\n{'─' * 64}\n  {title}\n{'─' * 64}")


async def _dry_run(
    factory: async_sessionmaker[AsyncSession], settings: Settings, event_id: int | None
) -> None:
    from whaledecode.application.services.investigation import build_investigation_service

    _, service, reasoner = build_investigation_service(settings)
    oracle = service._price_oracle  # noqa: SLF001  # ponytail: diagnostic tool, private access is the point

    event = await _pick_event(factory, event_id)
    print(f"Replaying pipeline for #{event.id} ({event.chain} {event.event_type}) "
          f"dedupe_key={event.dedupe_key}\n")

    # Step A: deterministic gate + price-oracle USD value.
    _banner("Step A — Price Oracle Resolution + $50k Whale Gate")
    passed = await process_and_gate_candidate(event, oracle, timestamp=event.created_at.timestamp())
    value = float(event.raw_json.get("value_usd", 0.0))
    print(f"  resolved value_usd = ${value:,.2f}  (floor = ${MIN_WHALE_THRESHOLD_USD:,.0f})")
    print(f"  gate verdict = {'PASS' if passed else 'DROP'} (skipped in worker)")
    if not passed:
        print("\n  Result: event would be marked 'skipped'; the pipeline stops here.")
        return

    # Step B: counterparty entity resolution + market context.
    _banner("Step B — Wallet Entity Resolution + Market Context")
    from whaledecode.application.services.investigation import sanitize_event_payload

    compact = sanitize_event_payload(event.raw_json)
    event_dict = event.model_dump()
    event_dict["raw_json"] = compact
    await service._enrich_market_context(event_dict)  # noqa: SLF001
    print(f"  from_label  = {event_dict.get('from_label')}")
    print(f"  to_label    = {event_dict.get('to_label')}")
    print(f"  category    = {event_dict.get('event_category')}")
    print(f"  asset       = {event_dict.get('asset')}")
    print(f"  total_value = ${float(event_dict.get('total_value_usd') or 0):,.2f}")

    # Step C: sentinel LLM reasoning node (live call, outside any DB txn).
    _banner("Step C — Sentinel LLM Reasoning Node (live call)")
    result = await reasoner.investigate_event(event_dict)
    summary = result.get("summary", "")
    print(f"  risk_score = {result.get('risk_score')}  latency_ms = {result.get('latency_ms')}")
    print(f"  summary    = {summary[:400]}{'…' if len(summary) > 400 else ''}")

    # Step D: channel alert decision gate (worker._channel_metrics + floors).
    _banner("Step D — Alert Creation Decision Gate")
    from whaledecode.application.worker import (
        CHANNEL_MIN_SCORE,
        CHANNEL_MIN_VALUE_USD,
    )

    score = int(float(result.get("risk_score", 0.0)) * 100)
    print(f"  score     = {score}   (channel floor = {CHANNEL_MIN_SCORE})")
    print(f"  value_usd = ${value:,.2f}   (channel floor = ${CHANNEL_MIN_VALUE_USD:,.0f})")
    if score < CHANNEL_MIN_SCORE:
        print("  verdict   = BELOW score floor → marked 'skipped', no alert")
    elif value < CHANNEL_MIN_VALUE_USD:
        print("  verdict   = BELOW value floor → marked 'skipped', no alert")
    else:
        print("  verdict   = WOULD DISPATCH a Telegram alert (dry run: nothing sent)")

    print("\n  Summary: ", end="")
    if result.get("status") == "skipped" or not summary:
        print("reasoner found nothing worth reporting; worker marks 'completed' without dispatch.")
    else:
        print("event would flow to the channel formatter (build_alert_data → format_alert).")

    await oracle.aclose()


# ------------------------------------------------------------- entry -------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="replay the pipeline in memory")
    parser.add_argument("--event-id", type=int, default=None, help="target a specific candidate event")
    args = parser.parse_args(argv)

    settings = _settings()
    setup_logging(settings)
    factory = _factory(settings)

    if args.dry_run:
        asyncio.run(_dry_run(factory, settings, args.event_id))
    else:
        asyncio.run(_report(factory))
    return 0


if __name__ == "__main__":
    sys.exit(main())

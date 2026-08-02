from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm_graph.formatting.sanitizer import sanitize_event_payload
from whaledecode.adapters.telegram.formatters.relay import RelayFormatter
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.agent_run import AgentRun
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.ports.reasoner import ReasonerPort
from whaledecode.domain.services.event_gate import EventGate


class InvestigationService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], reasoner: ReasonerPort, settings: Settings | None = None) -> None:
        self._uow_factory = uow_factory
        self._reasoner = reasoner
        self._relay = RelayFormatter(settings)
        self._gate = EventGate(
            min_score_threshold=settings.MIN_INVESTIGATION_SCORE if settings else 0.65,
            min_value_usd=settings.MIN_INVESTIGATION_VALUE_USD if settings else 5000.0,
        )

    async def process_event(self, event: CandidateEvent) -> dict[str, Any]:
        # Idempotent fast path: already investigated under this dedupe key → reuse stored analysis.
        async with self._uow_factory() as uow:
            existing = await uow.candidate_events.get_by_dedupe_key(event.dedupe_key)
            if existing is not None and existing.id is not None:
                run = await uow.agent_runs.get_by_trigger("event", existing.id)
                if run is not None and run.output_json:
                    return run.output_json

        # Stage 1: Deterministic gate — drop low-conviction / low-value events before the LLM.
        if not self._gate.should_investigate(event):
            event.status = "skipped"
            async with self._uow_factory() as uow:
                await self._persist_skipped(uow, event)
            return {"status": "skipped", "reason": "Below gate threshold"}

        # Stage 2: Payload sanitization — compact raw RPC data for token efficiency.
        compact_json = sanitize_event_payload(event.raw_json)
        event_dict = event.model_dump()
        event_dict["raw_json"] = compact_json

        # Reasoner call happens outside any DB transaction — don't hold a connection across an LLM call.
        result = await self._reasoner.investigate_event(event_dict)

        async with self._uow_factory() as uow:
            persisted = await self._persist_event(uow, event)
            assert persisted.id is not None, "candidate event must have an id after persistence"
            existing_run = await uow.agent_runs.get_by_trigger("event", persisted.id)
            if existing_run is None:
                run = AgentRun(
                    trigger_type="event",
                    trigger_ref_id=persisted.id,
                    graph_name="event_investigation",
                    status="completed",
                    input_json=event_dict,
                    output_json=result,
                    latency_ms=result.get("latency_ms", 0),
                )
                await uow.agent_runs.create(run)
            await uow.commit()
        return result

    @staticmethod
    async def _persist_skipped(uow: UnitOfWork, event: CandidateEvent) -> None:
        """Persist the skipped status, tolerating a concurrent insert on uq_candidate_dedupe."""
        try:
            await uow.candidate_events.update(event)
        except IntegrityError:
            await uow.rollback()
            existing = await uow.candidate_events.get_by_dedupe_key(event.dedupe_key)
            if existing is None:
                raise
            existing.status = "skipped"
            await uow.candidate_events.update(existing)
        await uow.commit()

    @staticmethod
    async def _persist_event(uow: UnitOfWork, event: CandidateEvent) -> CandidateEvent:
        """Get-or-create the candidate event, tolerating concurrent inserts on uq_candidate_dedupe."""
        try:
            return await uow.candidate_events.create(event)
        except IntegrityError:
            await uow.rollback()
            existing = await uow.candidate_events.get_by_dedupe_key(event.dedupe_key)
            if existing is None:
                raise
            return existing

    async def chat(self, user_message: str, context: dict[str, Any] | None = None) -> str:
        result = await self._reasoner.investigate_chat({"message": user_message, "context": context or {}})
        return self._relay.format_chat_response(result)

    async def generate_briefing(self, user_id: int) -> str:
        result = await self._reasoner.generate_briefing({"user_id": user_id})
        return self._relay.format_briefing(result)

from typing import Any

from whaledecode.adapters.telegram.formatters.relay import RelayFormatter
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.agent_run import AgentRun
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.ports.reasoner import ReasonerPort


class InvestigationService:
    def __init__(self, uow_factory, reasoner: ReasonerPort, settings: Settings | None = None) -> None:
        self._uow_factory = uow_factory
        self._reasoner = reasoner
        self._relay = RelayFormatter(settings)

    async def process_event(self, event: CandidateEvent) -> dict[str, Any]:
        event_dict = event.model_dump()
        result = await self._reasoner.investigate_event(event_dict)
        async with self._uow_factory() as uow:
            await uow.candidate_events.create(event)
            run = AgentRun(
                trigger_type="event",
                trigger_ref_id=event.id,
                graph_name="event_investigation",
                status="completed",
                input_json=event_dict,
                output_json=result,
                latency_ms=result.get("latency_ms", 0),
            )
            await uow.agent_runs.create(run)
            await uow.commit()
        return result

    async def chat(self, user_message: str, context: dict[str, Any] | None = None) -> str:
        result = await self._reasoner.investigate_chat({"message": user_message, "context": context or {}})
        return self._relay.format_chat_response(result)

    async def generate_briefing(self, user_id: int) -> str:
        result = await self._reasoner.generate_briefing({"user_id": user_id})
        return self._relay.format_briefing(result)

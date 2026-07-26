from typing import Any

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
from whaledecode.domain.entities.agent_run import AgentRun
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.reasoning_report import ReasoningReport


class InvestigationService:
    def __init__(self, uow: UnitOfWork, reasoner: LangGraphReasoner) -> None:
        self._uow = uow
        self._reasoner = reasoner

    async def process_event(self, event: CandidateEvent) -> dict[str, Any]:
        event_dict = event.model_dump()
        result = await self._reasoner.investigate_event(event_dict)
        await self._uow.candidate_events.create(event)
        run = AgentRun(
            trigger_type="event",
            trigger_ref_id=event.id,
            graph_name="event_investigation",
            status="completed",
            input_json=event_dict,
            output_json=result,
            latency_ms=result.get("latency_ms", 0),
        )
        created_run = await self._uow.agent_runs.create(run)
        report = ReasoningReport(
            agent_run_id=created_run.id,
            summary=result.get("summary", ""),
            risk_score=result.get("risk_score", 0.0),
            thesis=result.get("thesis", ""),
            evidence=result.get("evidence", []),
            tool_calls=result.get("tool_calls", []),
            disclaimer=result.get("disclaimer", ""),
        )
        await self._uow.admin_audit_logs.create(report)
        await self._uow.commit()
        return result

    async def chat(self, user_message: str, context: dict[str, Any] | None = None) -> str:
        result = await self._reasoner.investigate_chat({"message": user_message, "context": context or {}})
        return result.get("response", "I'm not sure how to answer that yet.")

    async def generate_briefing(self, user_id: int) -> str:
        result = await self._reasoner.generate_briefing({"user_id": user_id})
        return result.get("briefing", "No briefing available yet.")

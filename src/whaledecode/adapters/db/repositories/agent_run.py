import json

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.agent_run import AgentRunModel
from whaledecode.domain.entities.agent_run import AgentRun


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: AgentRun) -> AgentRun:
        model = AgentRunModel(
            trigger_type=run.trigger_type,
            trigger_ref_id=run.trigger_ref_id,
            graph_name=run.graph_name,
            status=run.status,
            input_json=json.dumps(run.input_json),
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            latency_ms=run.latency_ms,
            error=run.error,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(self, run: AgentRun) -> None:
        result = await self._session.execute(select(AgentRunModel).where(AgentRunModel.id == run.id))
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.status = run.status
        model.output_json = json.dumps(run.output_json) if run.output_json else None
        model.tokens_in = run.tokens_in
        model.tokens_out = run.tokens_out
        model.cost_usd = run.cost_usd
        model.latency_ms = run.latency_ms
        model.error = run.error
        model.completed_at = run.completed_at

    async def get_by_trigger(self, trigger_type: str, trigger_ref_id: int) -> AgentRun | None:
        result = await self._session.execute(
            select(AgentRunModel)
            .where(AgentRunModel.trigger_type == trigger_type)
            .where(AgentRunModel.trigger_ref_id == trigger_ref_id)
            .order_by(desc(AgentRunModel.created_at))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[AgentRun]:
        result = await self._session.execute(
            select(AgentRunModel).order_by(desc(AgentRunModel.created_at)).limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars()]

    def _to_domain(self, model: AgentRunModel) -> AgentRun:
        return AgentRun(
            id=model.id,
            trigger_type=model.trigger_type,
            trigger_ref_id=model.trigger_ref_id,
            graph_name=model.graph_name,
            status=model.status,
            input_json=json.loads(model.input_json) if isinstance(model.input_json, str) else {},
            output_json=json.loads(model.output_json) if model.output_json and isinstance(model.output_json, str) else None,
            tokens_in=model.tokens_in,
            tokens_out=model.tokens_out,
            cost_usd=model.cost_usd,
            latency_ms=model.latency_ms,
            error=model.error,
            created_at=model.created_at,
            completed_at=model.completed_at,
        )

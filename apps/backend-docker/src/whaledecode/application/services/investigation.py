import time
from collections.abc import Callable
from typing import Any

from aiolimiter import AsyncLimiter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.normalizer import transfer_amount
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm_graph.formatting.sanitizer import sanitize_event_payload
from whaledecode.adapters.telegram.formatters.relay import RelayFormatter
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.agent_run import AgentRun
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.ports.reasoner import ReasonerPort
from whaledecode.domain.services.event_gate import EventGate, process_and_gate_candidate


def _unpad_address(address: str) -> str:
    """Normalize a log-topics padded address (64 hex chars) to a 20-byte 0x string."""
    body = address[2:] if address.lower().startswith("0x") else address
    body = body.lower()
    return "0x" + body[-40:] if len(body) >= 40 else body


def _counterparty(event: dict[str, Any], side: str) -> str:
    """Best-effort extraction of the from/to address from webhook or RPC-log payloads."""
    raw = event.get("raw_json") if isinstance(event.get("raw_json"), dict) else {}
    keys = ("from", "fromAddress") if side == "from" else ("to", "toAddress")
    for key in keys:
        addr = raw.get(key) or event.get(key)
        if addr:
            return _unpad_address(str(addr))
    topics = raw.get("topics") or event.get("topics") or []
    idx = 1 if side == "from" else 2
    if len(topics) > idx and topics[idx]:
        return _unpad_address(str(topics[idx]))
    return ""


_CEX_KEYWORDS = (
    "binance",
    "coinbase",
    "kraken",
    "okx",
    "bybit",
    "bitget",
    "mexc",
    "gate.io",
    "gemini",
    "bitfinex",
    "kucoin",
    "huobi",
    "htx",
    "upbit",
    "bithumb",
    "crypto.com",
    "bitmart",
    "exchange",
    "hot wallet",
)
_COLD_KEYWORDS = ("cold", "treasury", "vault", "storage", "reserve", "custody")


def _wallet_kind(label: str, tags: list[str]) -> str:
    """Classify a curated wallet as CEX / cold storage / other from its label+tags."""
    text = f"{label} {' '.join(tags)}".lower()
    if any(k in text for k in _CEX_KEYWORDS):
        return "cex"
    if any(k in text for k in _COLD_KEYWORDS):
        return "cold"
    return "other"


def _event_category(from_kind: str, to_kind: str) -> str:
    """Derive the CEX-flow macro label the LLM should anchor on."""
    if from_kind == "cex" and to_kind == "cex":
        return "Inter-Exchange Transfer"
    if from_kind == "cex":
        return "CEX Outflow"
    if to_kind == "cex":
        return "CEX Inflow"
    return "Whale Transfer"


class InvestigationService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        reasoner: ReasonerPort,
        settings: Settings | None = None,
        rate_limit_rpm: int = 14,
        price_oracle: Any | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._reasoner = reasoner
        self._relay = RelayFormatter(settings)
        self._price_oracle = price_oracle
        self._gate = EventGate(
            min_score_threshold=settings.MIN_INVESTIGATION_SCORE if settings else 0.65,
            min_value_usd=settings.MIN_INVESTIGATION_VALUE_USD if settings else 5000.0,
        )
        # ponytail: per-instance leaky bucket on the investigation path only. Free-tier
        # quota is 15 RPM (14 + 1 margin) but the limiter is not shared across the
        # worker/bot processes and chat/briefing calls are ungated — tighten if quota
        # exhaustion still bites in production.
        self._rate_limiter = AsyncLimiter(rate_limit_rpm, 60.0)

    async def process_event(self, event: CandidateEvent) -> dict[str, Any]:
        # Idempotent fast path: already investigated under this dedupe key → reuse stored analysis.
        async with self._uow_factory() as uow:
            existing = await uow.candidate_events.get_by_dedupe_key(event.dedupe_key)
            if existing is not None and existing.id is not None:
                run = await uow.agent_runs.get_by_trigger("event", existing.id)
                if run is not None and run.output_json:
                    return run.output_json

        # Stage 1: Deterministic gate — drop low-conviction / low-value events before the LLM.
        # When a price oracle is wired in, the raw on-chain token amount is first priced
        # to a real USD value (at event time), replacing the placeholder stored at ingestion.
        if self._price_oracle is not None and not await process_and_gate_candidate(
            event, self._price_oracle, timestamp=time.time()
        ):
            event.status = "skipped"
            async with self._uow_factory() as uow:
                await self._persist_skipped(uow, event)
            return {"status": "skipped", "reason": "Below $50k USD gate"}
        if not self._gate.should_investigate(event):
            event.status = "skipped"
            async with self._uow_factory() as uow:
                await self._persist_skipped(uow, event)
            return {"status": "skipped", "reason": "Below gate threshold"}

        # Stage 2: Payload sanitization — compact raw RPC data for token efficiency.
        compact_json = sanitize_event_payload(event.raw_json)
        event_dict = event.model_dump()
        event_dict["raw_json"] = compact_json

        # Stage 2.5: Resolve counterparties to human-readable entity labels and derive
        # market context (CEX flow category) so the LLM reasons like a trader.
        await self._enrich_market_context(event_dict)

        # Reasoner call happens outside any DB transaction — don't hold a connection across an LLM call.
        async with self._rate_limiter:
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

    async def _enrich_market_context(self, event: dict[str, Any]) -> None:
        """Stamp entity labels + CEX flow category onto the event for the LLM.

        ``list_active`` is TTL-cached, so this is one cached query producing an
        in-memory (case-insensitive) address→label map. Unknown parties become
        "Unlabeled EOA" — never a bare hex string in the LLM context.
        """
        async with self._uow_factory() as uow:
            wallets = await uow.curated_wallets.list_active()
        labels = {w.address.lower(): (w.label, w.tags) for w in wallets}
        kinds = []
        for side in ("from", "to"):
            address = _counterparty(event, side)
            label, tags = labels.get(address, ("", []))
            kinds.append(_wallet_kind(label, tags))
            event[f"{side}_label"] = label or "Unlabeled EOA"
            event[f"{side}_entity"] = f"{event[f'{side}_label']} ({address[:6]}...{address[-4:]})" if address else event[f"{side}_label"]
        event["event_category"] = _event_category(*kinds)
        event["flow_type"] = event["event_category"]
        event["24h_vol_usd"] = "Unavailable"  # filled by dexscreener_tool when the LLM queries it
        # Exact token/asset/value facts the LLM must anchor on instead of guessing.
        raw = event.get("raw_json")
        if not isinstance(raw, dict):
            raw = {}
        event["token_amount"] = transfer_amount(raw)
        event["asset"] = raw.get("symbol") or raw.get("token") or raw.get("asset") or "Unknown Token"
        value_usd = float(event.get("raw_json", {}).get("value_usd") or 0.0)
        event["total_value_usd"] = value_usd

        # Oracle enrichment: real symbol, unit price at event time, and key price
        # levels for the LLM. All best-effort — a failure yields conservative
        # fallbacks ("Unknown Token") rather than fabricated numbers.
        if self._price_oracle is not None:
            contract_address = raw.get("address") or ""
            chain = event.get("chain") or "ethereum"
            symbol = await self._price_oracle.get_token_symbol(contract_address, chain)
            if symbol:
                event["asset"] = symbol
            price_at = await self._price_oracle.get_token_price_usd_at(contract_address, chain, time.time())
            if price_at > 0:
                event["price_at_timestamp"] = price_at
                event["total_value_usd"] = event["token_amount"] * price_at
            levels = await self._price_oracle.get_price_levels(contract_address, chain)
            if levels:
                event["price_levels"] = levels

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

    async def chat(self, user_message: str, context: dict[str, Any] | None = None, thread_id: str | None = None) -> str:
        result = await self._reasoner.investigate_chat(
            {"message": user_message, "context": context or {}, "thread_id": thread_id}
        )
        return self._relay.format_chat_response(result)

    async def generate_briefing(self, user_id: int) -> str:
        result = await self._reasoner.generate_briefing({"user_id": user_id})
        return self._relay.format_briefing(result)


def build_investigation_service(
    settings: Settings,
) -> tuple[async_sessionmaker[AsyncSession], InvestigationService, ReasonerPort]:
    """Wire DB session + LLM graph into an InvestigationService."""
    from whaledecode.adapters.db.session import create_session_factory
    from whaledecode.adapters.llm.factory import LLMFactory
    from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
    from whaledecode.adapters.pricing.oracle import PriceOracle

    session_factory = create_session_factory(settings)
    llm_factory = LLMFactory(settings)
    reasoner = LangGraphReasoner(settings, llm_factory)
    return (
        session_factory,
        InvestigationService(
            lambda: UnitOfWork(session_factory),
            reasoner,
            settings,
            price_oracle=PriceOracle(),
        ),
        reasoner,
    )

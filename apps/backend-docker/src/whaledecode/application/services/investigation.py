import asyncio
import time
from collections.abc import Callable
from typing import Any

import structlog
from aiolimiter import AsyncLimiter
from cachetools import TTLCache  # type: ignore[import-untyped]
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.chain.normalizer import transfer_amount
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm_graph.formatting.sanitizer import sanitize_event_payload
from whaledecode.adapters.telegram.formatters.relay import RelayFormatter
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.agent_run import AgentRun
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.policies.conviction import Purchase, score_conviction
from whaledecode.domain.ports.reasoner import ReasonerPort
from whaledecode.domain.services.event_gate import EventGate, process_and_gate_candidate

log = structlog.get_logger()


def _unpad_address(address: str) -> str:
    """Normalize a log-topics padded address (64 hex chars) to a 20-byte 0x string."""
    body = address[2:] if address.lower().startswith("0x") else address
    body = body.lower()
    return "0x" + body[-40:] if len(body) >= 40 else body


def _opt_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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
        profiler: Any | None = None,
        graph_tracer: Any | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._reasoner = reasoner
        self._settings = settings
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
        # DexScreener pool-TVL cache (Module 3): (chain:token) -> tvl_usd, 5 min TTL
        # — same staleness budget as the price oracle.
        self._pool_tvl_cache: TTLCache[str, float] = TTLCache(maxsize=512, ttl=300)
        self._profiler = profiler
        self._graph_tracer = graph_tracer

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
            log.info(f"[FILTER_SKIP] Event ID={event.id} marked as skipped. Reason='Below $50k USD gate' | Tx={event.tx_hash}")
            return {"status": "skipped", "reason": "Below $50k USD gate"}
        if not self._gate.should_investigate(event):
            event.status = "skipped"
            async with self._uow_factory() as uow:
                await self._persist_skipped(uow, event)
            log.info(f"[FILTER_SKIP] Event ID={event.id} marked as skipped. Reason='Below gate threshold' | Tx={event.tx_hash}")
            return {"status": "skipped", "reason": "Below gate threshold"}

        # Stage 2: Payload sanitization — compact raw RPC data for token efficiency.
        compact_json = sanitize_event_payload(event.raw_json)
        event_dict = event.model_dump()
        event_dict["raw_json"] = compact_json

        # Stage 2.5: Resolve counterparties to human-readable entity labels and derive
        # market context (CEX flow category) so the LLM reasons like a trader.
        await self._enrich_market_context(event_dict)
        # Edge Intelligence fast path (deterministic pre-enrichment, no blocking
        # third-party calls), then spawn the multi-hop cluster trace as a
        # prefetch task — it runs concurrently with the LLM synthesis below.
        await self._enrich_edge_intelligence(event_dict)
        trace_task = self._spawn_cluster_trace(event_dict)

        # Reasoner call happens outside any DB transaction — don't hold a connection across an LLM call.
        model_name = self._settings.MODEL_HEAVY_REASONING if self._settings else "heavy_reasoning"
        log.info(f"[LLM_SYNTHESIS] Generating analysis for Event ID={event.id} via model={model_name}...")
        async with self._rate_limiter:
            result = await self._reasoner.investigate_event(event_dict)
        log.info(
            f"[LLM_SYNTHESIS] Completed analysis for Event ID={event.id} "
            f"in {result.get('latency_ms', 0)}ms"
        )
        if trace_task is not None:
            # The trace had the whole LLM latency to finish; cap the wait so a
            # slow RPC can never stall dispatch.
            try:
                await asyncio.wait_for(asyncio.shield(trace_task), timeout=5.0)
            except (asyncio.TimeoutError, Exception) as exc:
                log.warning(f"[EDGE_INTEL] cluster trace incomplete: {exc}")
                trace_task.cancel()
        # Copy deterministic enrichment onto the persisted entity.
        self._sync_intel_fields(event, event_dict)

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
            kind = _wallet_kind(label, tags)
            kinds.append(kind)
            event[f"{side}_label"] = label or "Unlabeled EOA"
            event[f"{side}_category"] = {"cex": "CEX", "cold": "Cold Storage"}.get(kind, label or "Unlabeled EOA")
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

    async def _enrich_edge_intelligence(self, event: dict[str, Any]) -> None:
        """Modules 1-3 fast enrichment. Deterministic, additive, fail-soft.

        Only cached reads + one cached DexScreener call — the multi-hop trace
        is spawned separately as a prefetch task (zero-latency critical path).
        """
        raw_value = event.get("raw_json")
        raw: dict[str, Any] = dict(raw_value) if isinstance(raw_value, dict) else {}
        token = str(raw.get("address") or "").lower()
        chain = str(event.get("chain") or "")
        now_unix = time.time()
        labels: dict[str, str] = {}
        try:
            async with self._uow_factory() as uow:
                wallets = await uow.curated_wallets.list_active()
            labels = {w.address.lower(): (w.label or w.category) for w in wallets}
        except Exception as exc:
            log.warning(f"[EDGE_INTEL] curated wallet lookup failed: {exc}")
        event["_known_labels"] = labels

        # Module 3a — Pool Impact Ratio (DexScreener TVL, cached).
        value_usd = float(raw.get("value_usd") or 0.0)
        pool_tvl = await self._pool_tvl_usd(chain, token) if token else 0.0
        purchases = await self._recent_smart_purchases(token, now_unix, set(labels))
        conviction = score_conviction(value_usd, pool_tvl, purchases, now_unix, smart_wallets=set(labels))
        event["conviction"] = conviction.to_context()
        event["pool_impact_percentage"] = round(conviction.pool_impact_ratio * 100, 3) if pool_tvl > 0 else None
        event["coordinated_flag"] = conviction.coordinated_wallets > 0
        if conviction.badges:
            event["intel_badges"] = conviction.badges

        # Module 1 — behavioral profile (one cached read; cold miss returns a
        # baseline instantly and backfills in the background).
        if self._profiler is not None:
            wallet_addr = _counterparty(event, "to")
            try:
                event.update(await self._profiler.enrich(chain, wallet_addr))
            except Exception as exc:
                log.warning(f"[EDGE_INTEL] profiler enrich failed: {exc}")

    def _spawn_cluster_trace(self, event: dict[str, Any]) -> asyncio.Task | None:
        """Module 2 prefetch: multi-hop funding attribution for unlabeled actors.

        Runs while the LLM synthesizes (~seconds), so the ~1-3s Alchemy BFS adds
        zero wall-clock latency to the alert pipeline."""
        if self._graph_tracer is None:
            return None
        from_addr = _counterparty(event, "from")
        labels = event.get("_known_labels") or {}
        if not from_addr or from_addr in labels:
            return None

        async def _run() -> None:
            trace = await self._graph_tracer.trace(
                str(event.get("chain") or ""),
                from_addr,
                known_labels=labels,
                now_unix=time.time(),
            )
            if trace.attributed_label:
                cluster = f"Child of {trace.attributed_label}"
                if trace.stealth_accumulation:
                    cluster += f" [stealth cluster of {trace.siblings_in_cluster} wallets]"
                event["funding_attribution"] = cluster
                event["cluster_origin"] = trace.attributed_label
                event["hop_count"] = trace.hops
            event.pop("_known_labels", None)

        return asyncio.create_task(_run())

    @staticmethod
    def _sync_intel_fields(event: CandidateEvent, event_dict: dict[str, Any]) -> None:
        """Copy deterministic Edge Intelligence fields onto the persisted entity."""
        event.win_rate = _opt_float(event_dict.get("wallet_win_rate_30d"))
        event.pool_impact_percentage = _opt_float(event_dict.get("pool_impact_percentage"))
        event.cluster_origin = event_dict.get("cluster_origin") or None
        event.hop_count = event_dict.get("hop_count")
        event.coordinated_flag = bool(event_dict.get("coordinated_flag"))

    async def _pool_tvl_usd(self, chain: str, token: str) -> float:
        """Deepest DexScreener pool liquidity for ``token`` on ``chain`` (0.0 unknown)."""
        key = f"{chain.lower()}:{token}"
        cached = self._pool_tvl_cache.get(key)
        if cached is not None:
            return float(cached)
        try:
            import httpx

            client = httpx.AsyncClient(timeout=5.0)
            try:
                response = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}")
                response.raise_for_status()
                pairs = response.json().get("pairs") or []
            finally:
                await client.aclose()
        except Exception as exc:
            log.warning(f"[EDGE_INTEL] dexscreener tvl failed for {token}: {exc}")
            return 0.0
        chain_slug = {"ethereum": "ethereum", "eth": "ethereum", "arbitrum": "arbitrum", "arb": "arbitrum", "base": "base"}
        want = chain_slug.get(chain.lower(), "")
        best = 0.0
        for pair in pairs:
            if want and str(pair.get("chainId", "")).lower() != want:
                continue
            best = max(best, float((pair.get("liquidity") or {}).get("usd") or 0.0))
        if best > 0:
            self._pool_tvl_cache[key] = best
        return best

    async def _recent_smart_purchases(self, token: str, now_unix: float, smart_addresses: set[str]) -> list[Purchase]:
        """SWAPs of ``token`` in the coordination window by known smart wallets."""
        if not token or not smart_addresses:
            return []
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(minutes=60)
        async with self._uow_factory() as uow:
            rows = await uow.candidate_events.recent_swaps_for_token(token, since)
            wallet_ids = {r.wallet_id for r in rows}
            addr_by_id: dict[int, str] = {}
            for wid in wallet_ids:
                wallet = await uow.curated_wallets.get(wid) if wid is not None else None
                if wallet is not None and wallet.id is not None:
                    addr_by_id[wallet.id] = wallet.address.lower()
        return [
            Purchase(addr_by_id[r.wallet_id], token, r.chain, r.created_at.timestamp())
            for r in rows
            if r.created_at and r.wallet_id in addr_by_id
        ]

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

    async def chat(self, user_message: str, context: dict[str, Any] | None = None, thread_id: str | None = None, model: str = "chat") -> str:
        result = await self._reasoner.investigate_chat(
            {"message": user_message, "context": context or {}, "thread_id": thread_id},
            model=model,
        )
        return self._relay.format_chat_response(result)

    async def generate_briefing(self, user_id: int) -> str:
        result = await self._reasoner.generate_briefing({"user_id": user_id})
        return self._relay.format_briefing(result)


def build_investigation_service(
    settings: Settings,
) -> tuple[async_sessionmaker[AsyncSession], InvestigationService, ReasonerPort]:
    """Wire DB session + LLM graph into an InvestigationService."""
    from whaledecode.adapters.alchemy.transfers import AlchemyTransfersClient
    from whaledecode.adapters.arkham.client import ArkhamClient
    from whaledecode.adapters.db.session import create_session_factory
    from whaledecode.adapters.llm.factory import LLMFactory
    from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
    from whaledecode.adapters.pricing.oracle import PriceOracle
    from whaledecode.services.behavioral_profiler import BehavioralProfiler
    from whaledecode.services.graph_tracer import GraphTracer

    session_factory = create_session_factory(settings)
    llm_factory = LLMFactory(settings)
    reasoner = LangGraphReasoner(settings, llm_factory)
    price_oracle = PriceOracle()
    uow_factory = lambda: UnitOfWork(session_factory)  # noqa: E731
    arkham = ArkhamClient(
        settings.ARKHAM_API_KEY.get_secret_value() if settings.ARKHAM_API_KEY else ""
    )
    profiler = BehavioralProfiler(uow_factory, price_oracle, arkham)
    graph_tracer = GraphTracer(uow_factory, AlchemyTransfersClient.from_settings(settings))
    return (
        session_factory,
        InvestigationService(
            lambda: UnitOfWork(session_factory),
            reasoner,
            settings,
            price_oracle=price_oracle,
            profiler=profiler,
            graph_tracer=graph_tracer,
        ),
        reasoner,
    )

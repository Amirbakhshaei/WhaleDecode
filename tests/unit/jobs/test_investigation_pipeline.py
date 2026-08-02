from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.domain.value_objects.hash import Hash

WALLET_ADDRESS = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
TX_HASH = "0x" + "a" * 64


class FakeReasoner:
    def __init__(self) -> None:
        self.investigate_calls = 0

    async def investigate_event(self, event_input: dict[str, Any]) -> dict[str, Any]:
        self.investigate_calls += 1
        return {
            "summary": "Whale moved 1M USDC to Binance",
            "risk_score": 0.85,
            "thesis": "Distribution",
            "evidence": [{"fact": "Transfer detected", "source": "etherscan"}],
            "tool_calls": [],
            "disclaimer": "DYOR",
            "latency_ms": 5,
        }

    async def investigate_chat(self, chat_input: dict[str, Any]) -> dict[str, Any]:
        return {"summary": "chat"}

    async def generate_briefing(self, briefing_input: dict[str, Any]) -> dict[str, Any]:
        return {"summary": "briefing"}


class FakeProvider:
    async def get_block_number(self, chain: str) -> int:
        return 20_000_000

    async def get_logs(
        self,
        chain: str,
        addresses: list[str],
        from_block: int,
        to_block: int,
        topics: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "address": WALLET_ADDRESS,
                "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"],
                "data": hex(200_000 * 10**18),
                "blockNumber": hex(from_block + 1),
                "transactionHash": TX_HASH,
                "logIndex": "0x0",
            }
        ]

    async def get_token_metadata(self, chain: str, address: str) -> dict[str, Any]:
        return {"name": "T", "symbol": "T", "decimals": 18}

    async def trace_call(self, chain: str, tx_hash: str) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        pass


def _settings() -> Settings:
    from pydantic import SecretStr

    return Settings(
        BOT_TOKEN=SecretStr("test"),
        GROQ_API_KEY=SecretStr("test"),
        ALERT_SCORE_THRESHOLD=0.3,
    )


async def _seed_wallet(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with UnitOfWork(session_factory) as uow:
        wallet = await uow.curated_wallets.create(
            CuratedWallet(address=WALLET_ADDRESS, chain=Chain.ETH, label="Test Whale")
        )
        await uow.commit()
        assert isinstance(wallet.id, int)
        return wallet.id


def _candidate_event(wallet_id: int) -> CandidateEvent:
    return CandidateEvent(
        wallet_id=wallet_id,
        chain="Ethereum",
        tx_hash=Hash(TX_HASH),
        log_index=0,
        block_number=100,
        event_type="TRANSFER",
        raw_json={"transactionHash": TX_HASH},
        score=40.0,
        dedupe_key="1:test:0",
    )


@pytest.mark.asyncio
async def test_process_event_persists_agent_run(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wallet_id = await _seed_wallet(session_factory)
    reasoner = FakeReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)

    result = await service.process_event(_candidate_event(wallet_id))

    assert reasoner.investigate_calls == 1
    assert result["summary"] == "Whale moved 1M USDC to Binance"

    async with UnitOfWork(session_factory) as uow:
        event = await uow.candidate_events.get_by_dedupe_key("1:test:0")
        assert event is not None and event.id is not None
        run = await uow.agent_runs.get_by_trigger("event", event.id)
        assert run is not None
        assert run.status == "completed"
        assert run.trigger_ref_id == event.id
        assert run.output_json == result


@pytest.mark.asyncio
async def test_process_event_idempotent_skips_reasoner(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wallet_id = await _seed_wallet(session_factory)
    reasoner = FakeReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)
    event = _candidate_event(wallet_id)

    await service.process_event(event)
    cached = await service.process_event(event)

    assert reasoner.investigate_calls == 1
    assert cached["summary"] == "Whale moved 1M USDC to Binance"


@pytest.mark.asyncio
async def test_process_event_skipped_when_below_gate_threshold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wallet_id = await _seed_wallet(session_factory)
    reasoner = FakeReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)

    event = _candidate_event(wallet_id)
    event.score = 0.1

    result = await service.process_event(event)

    assert reasoner.investigate_calls == 0
    assert result == {"status": "skipped", "reason": "Below gate threshold"}

    async with UnitOfWork(session_factory) as uow:
        persisted = await uow.candidate_events.get_by_dedupe_key("1:test:0")
        assert persisted is not None
        assert persisted.status == "skipped"


@pytest.mark.asyncio
async def test_poll_wallets_runs_reasoner_and_persists_agent_run(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    from whaledecode.jobs.poll_wallets import poll_wallets

    await _seed_wallet(session_factory)
    monkeypatch.setattr("whaledecode.jobs.poll_wallets.create_chain_provider", lambda settings: FakeProvider())

    reasoner = FakeReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)
    await poll_wallets(session_factory, _settings(), service)

    async with UnitOfWork(session_factory) as uow:
        events = await uow.candidate_events.list_by_status("NEW")
        assert len(events) == 1
        assert isinstance(events[0].id, int)
        run = await uow.agent_runs.get_by_trigger("event", events[0].id)
        assert run is not None
        assert run.status == "completed"
        assert run.output_json is not None
        assert run.output_json["summary"] == "Whale moved 1M USDC to Binance"

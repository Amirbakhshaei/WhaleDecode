import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.chain.normalizer import TRANSFER_EVENT_SIGNATURE, pad_address_to_topic
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.domain.value_objects.hash import Hash

WALLET_ADDRESS = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
TOKEN_ADDRESS = "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503"
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
        raw_json={"transactionHash": TX_HASH, "value_usd": 100_000.0},
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
async def test_process_event_enriches_llm_payload_with_labels_and_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The event dict handed to the reasoner carries entity labels + CEX flow category."""
    async with UnitOfWork(session_factory) as uow:
        wallet = await uow.curated_wallets.create(
            CuratedWallet(address="0x28c6c06298d514db089934071355e5743bf21d60", chain=Chain.ETH, label="Binance 16")
        )
        await uow.commit()
        assert isinstance(wallet.id, int)

    class _CapturingReasoner(FakeReasoner):
        def __init__(self) -> None:
            super().__init__()
            self.captured: dict[str, Any] | None = None

        async def investigate_event(self, event_input: dict[str, Any]) -> dict[str, Any]:
            self.captured = event_input
            return await super().investigate_event(event_input)

    reasoner = _CapturingReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)
    event = _candidate_event(wallet.id)
    event.raw_json = {
        "from": "0x503828976d22510aad0201ac7ec88293211d23da",
        "to": "0x28c6c06298d514db089934071355e5743bf21d60",
        "value_usd": 100_000.0,
    }

    await service.process_event(event)

    assert reasoner.captured is not None
    assert reasoner.captured["from_label"] == "Unlabeled EOA"
    assert reasoner.captured["to_label"] == "Binance 16"
    assert reasoner.captured["event_category"] == "CEX Inflow"
    assert reasoner.captured["24h_vol_usd"] == "Unavailable"
    assert reasoner.captured["from_entity"] == "Unlabeled EOA (0x5038...23da)"
    assert reasoner.captured["to_entity"] == "Binance 16 (0x28c6...1d60)"


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
async def test_process_event_skips_existing_pending_row_without_missing_greenlet(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A pending row already in the DB (score 0.0 ingest bug) must be marked skipped
    via update() without triggering MissingGreenlet."""
    wallet_id = await _seed_wallet(session_factory)
    reasoner = FakeReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)

    event = _candidate_event(wallet_id)
    event.score = 0.1
    async with UnitOfWork(session_factory) as uow:
        await uow.candidate_events.create_pending(
            {
                "wallet_id": wallet_id,
                "chain": "Ethereum",
                "tx_hash": str(event.tx_hash),
                "log_index": 0,
                "block_number": 100,
                "event_type": "TRANSFER",
                "raw_json": {"value_usd": 100.0},
                "score": 0.1,
                "dedupe_key": event.dedupe_key,
            }
        )
        await uow.commit()

    result = await service.process_event(event)

    assert result == {"status": "skipped", "reason": "Below gate threshold"}
    async with UnitOfWork(session_factory) as uow:
        persisted = await uow.candidate_events.get_by_dedupe_key(event.dedupe_key)
    assert persisted is not None
    assert persisted.status == "skipped"


@pytest.mark.asyncio
async def test_webhook_activity_investigates_and_persists_agent_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from whaledecode.entrypoints.webhook import _activity_candidate, _score_candidate

    wallet_id = await _seed_wallet(session_factory)
    reasoner = FakeReasoner()
    service = InvestigationService(lambda: UnitOfWork(session_factory), reasoner)

    activity: dict[str, Any] = {
        "blockNum": "0xdf34a3",
        "hash": TX_HASH,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": WALLET_ADDRESS,
        "value": 2_000_000.0,
        "asset": "USDC",
        "category": "token",
        "rawContract": {"address": TOKEN_ADDRESS, "decimals": 6},
        "log": {
            "address": TOKEN_ADDRESS,
            "topics": [
                TRANSFER_EVENT_SIGNATURE,
                pad_address_to_topic("0x503828976d22510aad0201ac7ec88293211d23da"),
                pad_address_to_topic(WALLET_ADDRESS),
            ],
            "logIndex": "0x0",
            "blockNumber": "0xdf34a3",
            "transactionHash": TX_HASH,
        },
    }
    wallet = CuratedWallet(id=wallet_id, address=WALLET_ADDRESS, chain=Chain.ETH, label="Test Whale")
    candidate = _activity_candidate(activity, Chain.ETH, wallet)
    candidate.score = _score_candidate(candidate)
    assert candidate.event_type == "TRANSFER"
    assert candidate.dedupe_key == f"{wallet_id}:{TX_HASH}:0"
    assert candidate.score >= 50.0

    result = await service.process_event(candidate)

    assert reasoner.investigate_calls == 1
    assert result["summary"] == "Whale moved 1M USDC to Binance"

    async with UnitOfWork(session_factory) as uow:
        events = await uow.candidate_events.list_by_status("NEW")
        assert len(events) == 1
        assert isinstance(events[0].id, int)
        run = await uow.agent_runs.get_by_trigger("event", events[0].id)
        assert run is not None
        assert run.status == "completed"
        assert run.output_json is not None
        assert run.output_json["summary"] == "Whale moved 1M USDC to Binance"


@pytest.mark.asyncio
async def test_rate_limiter_blocks_burst_beyond_rpm(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wallet_id = await _seed_wallet(session_factory)
    reasoner = FakeReasoner()
    service = InvestigationService(
        lambda: UnitOfWork(session_factory), reasoner, rate_limit_rpm=1
    )

    first = await service.process_event(_candidate_event(wallet_id))
    assert reasoner.investigate_calls == 1
    assert first["summary"] == "Whale moved 1M USDC to Binance"

    second_event = _candidate_event(wallet_id)
    second_event.dedupe_key = "1:test:1"
    second_event.raw_json = {"transactionHash": TX_HASH, "value_usd": 100_000.0}

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(service.process_event(second_event), timeout=0.5)
    assert reasoner.investigate_calls == 1

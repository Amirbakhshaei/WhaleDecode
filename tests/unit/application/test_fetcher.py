import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from whaledecode.adapters.chain.normalizer import TRANSFER_EVENT_SIGNATURE, pad_address_to_topic
from whaledecode.application import fetcher as fetcher_module
from whaledecode.application.fetcher import LiveBlockchainFetcher
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain

TOKEN_ADDRESS = "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503"


def _settings(**overrides: Any) -> Settings:
    base = {
        "BOT_TOKEN": SecretStr("test"),
        "GROQ_API_KEY": SecretStr("test"),
        "ALERT_SCORE_THRESHOLD": 0.3,
        "POLL_INTERVAL_SECONDS": 0,
    }
    base.update(overrides)
    return Settings(**base)


def _log(wallet_address: str) -> dict:
    return {
        "address": TOKEN_ADDRESS,
        "topics": [
            TRANSFER_EVENT_SIGNATURE,
            pad_address_to_topic(wallet_address),
            None,
        ],
        "data": hex(200_000 * 10**18),
        "blockNumber": hex(100),
        "transactionHash": "0x" + "b" * 64,
        "logIndex": "0x0",
    }


class FakeProvider:
    def __init__(self, logs: list[dict] | None = None, *, fail_block: bool = False) -> None:
        self._logs = logs or []
        self._fail_block = fail_block

    async def get_block_number(self, chain: str) -> int:
        if self._fail_block:
            raise RuntimeError("rpc down")
        return 100

    async def get_logs(
        self, chain: str, addresses: list[str], from_block: int, to_block: int, topics: list[str] | None = None
    ) -> list[dict]:
        return self._logs


def test_fetcher_module_has_no_llm_dependencies() -> None:
    src = Path(fetcher_module.__file__).read_text()
    assert "InvestigationService" not in src
    assert "llm_graph" not in src
    assert "langchain" not in src
    assert "reasoner" not in src
    assert not any(name.startswith("Investigation") for name in dir(fetcher_module))


@pytest.mark.asyncio
async def test_poll_once_inserts_pending_event(session_factory, sample_address) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork

    async with UnitOfWork(session_factory) as uow:
        await uow.curated_wallets.create(
            CuratedWallet(address=sample_address, chain=Chain.ETH, label="Whale")
        )
        await uow.commit()

    fetcher = LiveBlockchainFetcher(session_factory, _settings())
    fetcher._provider = FakeProvider([_log(sample_address)])

    await fetcher.poll_once()

    async with UnitOfWork(session_factory) as uow:
        events = await uow.candidate_events.claim_next_pending(limit=10)
    assert len(events) == 1
    assert events[0].status == "pending"
    assert events[0].dedupe_key == f"1:{'0x' + 'b' * 64}:0"


@pytest.mark.asyncio
async def test_poll_once_drops_below_threshold_logs(session_factory, sample_address) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork

    async with UnitOfWork(session_factory) as uow:
        await uow.curated_wallets.create(
            CuratedWallet(address=sample_address, chain=Chain.ETH, label="Whale")
        )
        await uow.commit()

    low_value = _log(sample_address)
    low_value["data"] = hex(1 * 10**18)  # $1 → sentinel score below threshold
    fetcher = LiveBlockchainFetcher(session_factory, _settings())
    fetcher._provider = FakeProvider([low_value])

    await fetcher.poll_once()

    async with UnitOfWork(session_factory) as uow:
        events = await uow.candidate_events.claim_next_pending(limit=10)
    assert events == []


@pytest.mark.asyncio
async def test_poll_once_skips_when_no_wallets(session_factory) -> None:
    fetcher = LiveBlockchainFetcher(session_factory, _settings())
    fetcher._provider = FakeProvider([_log("0x")])

    await fetcher.poll_once()  # no wallets → no provider calls


@pytest.mark.asyncio
async def test_run_survives_provider_errors_and_stops(session_factory, sample_address) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork

    async with UnitOfWork(session_factory) as uow:
        await uow.curated_wallets.create(
            CuratedWallet(address=sample_address, chain=Chain.ETH, label="Whale")
        )
        await uow.commit()

    fetcher = LiveBlockchainFetcher(session_factory, _settings())
    fetcher._provider = FakeProvider([], fail_block=True)

    stop = asyncio.Event()
    task = asyncio.create_task(fetcher.run(stop))
    await asyncio.sleep(0.05)
    assert not task.done()

    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert task.done()

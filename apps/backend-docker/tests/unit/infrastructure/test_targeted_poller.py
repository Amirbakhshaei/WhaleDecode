"""Targeted failover poller: failover, tx aggregation, USD gating, idempotency."""
import pytest
from whaledecode.adapters.chain.evm_poller import EvmTargetedPoller
from whaledecode.adapters.chain.solana_poller import SolanaTargetedPoller
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter


def _wallet(addr: str, wid: int = 1) -> CuratedWallet:
    return CuratedWallet(id=wid, address=addr, chain=Chain.BASE)


class FakeRouter:
    """Records payloads; serves canned responses; can fail N nodes first."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads: list[dict] = []
        self.fail_first = 0

    async def post(self, payload):
        self.payloads.append(payload)
        if self.fail_first > 0:
            self.fail_first -= 1
            raise TimeoutError("node down")
        if payload["method"] == "eth_call":  # decimals()
            return "0x06"  # 6 decimals
        return self.responses.pop(0)

    async def aclose(self):
        pass


class FakeOracle:
    """$1 per unit — deterministic USD math."""

    def __init__(self):
        self.calls = []

    async def get_token_price_usd(self, contract_address: str, chain: str) -> float:
        self.calls.append((contract_address, chain))
        return 1.0

    async def aclose(self):
        pass


SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WALLET = "0x" + "a" * 40
PADDED = "0x" + "0" * 24 + "a" * 40


def _transfer_log(tx_hash: str, data_hex: str, log_index: int = 0) -> dict:
    return {
        "address": "0xtoken",
        "topics": [SIG, PADDED, None],
        "data": data_hex,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": "0x10",
    }


@pytest.mark.asyncio
async def test_evm_pushes_curated_set_into_topics_and_aggregates_per_tx():
    # Same tx in three logs (routing hop): 100 + 200 units of a 6-decimal token.
    logs = [
        _transfer_log("0xtx1", hex(100), 0),
        _transfer_log("0xtx1", hex(200), 1),
        _transfer_log("0xtx1", hex(50), 2),
        _transfer_log("0xtx2", hex(999), 3),
    ]
    router = FakeRouter(["0x20", logs, []])
    oracle = FakeOracle()
    poller = EvmTargetedPoller("BASE", "Base", router, price_oracle=oracle)  # type: ignore[arg-type]

    activities = await poller.fetch_recent_activity([_wallet(WALLET)])

    # Server-side filtering: curated set injected into topics.
    getlogs = [p for p in router.payloads if p["method"] == "eth_getLogs"]
    assert len(getlogs) == 2
    assert PADDED in getlogs[0]["params"][0]["topics"][1]

    # Aggregation: exactly one activity per tx_hash, net USD summed.
    by_tx = {a["tx_hash"]: a for a in activities}
    assert sorted(by_tx) == ["0xtx1", "0xtx2"]
    assert by_tx["0xtx1"]["value_usd"] == pytest.approx((100 + 200 + 50) / 10**6)
    assert by_tx["0xtx2"]["value_usd"] == pytest.approx(999 / 10**6)
    assert all(a["dedupe_key"].endswith(":agg") for a in activities)
    assert len({a["dedupe_key"] for a in activities}) == len(activities)


@pytest.mark.asyncio
async def test_solana_dedupes_signatures_across_polls():
    sigs = [{"signature": "sig1", "slot": 100, "err": None},
            {"signature": "sig2", "slot": 99, "err": None}]
    router = FakeRouter([sigs, [sigs[0]]])
    poller = SolanaTargetedPoller(router)  # type: ignore[arg-type]

    first = await poller.fetch_recent_activity([_wallet("SolAddr1", wid=7)])
    second = await poller.fetch_recent_activity([_wallet("SolAddr1", wid=7)])

    assert {a["tx_hash"] for a in first} == {"sig1", "sig2"}
    assert second == []  # idempotent re-poll: nothing new
    assert all(a["chain"] == "Solana" for a in first)


def test_router_cooldown_skips_dead_node():
    urls = ["http://dead", "http://alive"]

    class FakeResp:
        def __init__(self, status_code, json_body):
            self.status_code = status_code
            self._json = json_body

        def raise_for_status(self):
            pass

        def json(self):
            return self._json

    calls = []

    class FlakyClient:
        async def post(self, url, json=None):
            calls.append(url)
            if url == "http://dead":
                return FakeResp(429, {})
            return FakeResp(200, {"result": "ok"})

    router = RpcFailoverRouter("test", urls)
    router._client = FlakyClient()  # type: ignore[assignment]

    import asyncio

    result = asyncio.run(router.post({"method": "x"}))
    assert result == "ok"
    assert calls == ["http://dead", "http://alive"]  # failover happened

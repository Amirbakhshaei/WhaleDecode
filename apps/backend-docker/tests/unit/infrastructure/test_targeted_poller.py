"""Targeted failover poller: failover, server-side filtering, idempotency."""
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
        return self.responses.pop(0)

    async def aclose(self):
        pass


SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WALLET = "0x" + "a" * 40
PADDED = "0x" + "0" * 24 + "a" * 40


@pytest.mark.asyncio
async def test_evm_pushes_curated_set_into_topics():
    log = {
        "address": "0xtoken", "topics": [SIG, PADDED, None],
        "data": "0x64", "transactionHash": "0xhash", "logIndex": "0x1",
        "blockNumber": "0x10",
    }
    router = FakeRouter(["0x20", [log], []])  # blockNumber, outgoing logs, incoming logs
    poller = EvmTargetedPoller("BASE", "Base", router)  # type: ignore[arg-type]

    activities = await poller.fetch_recent_activity([_wallet(WALLET)])

    getlogs = [p for p in router.payloads if p["method"] == "eth_getLogs"]
    assert len(getlogs) == 2  # one query per transfer direction
    topics = getlogs[0]["params"][0]["topics"]
    # The curated set is pushed into the filter — node filters server-side.
    assert topics[0] == SIG and PADDED in topics[1]
    assert len(activities) == 1
    assert activities[0]["wallet_id"] == 1 and activities[0]["chain"] == "Base"
    assert activities[0]["dedupe_key"] == "1:0xhash:1"


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

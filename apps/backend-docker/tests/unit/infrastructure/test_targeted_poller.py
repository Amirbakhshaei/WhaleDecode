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

    first = await poller.fetch_recent_activity([_wallet("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2", wid=7)])
    second = await poller.fetch_recent_activity([_wallet("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2", wid=7)])

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


def test_router_fails_over_on_cloudflare_521_and_capacity_errors():
    """Regression: 521s and node-policy RPC errors must rotate, not crash the poll."""
    import asyncio

    class Resp:
        def __init__(self, status_code=200, body=None):
            self.status_code = status_code
            self._body = body or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    calls = []

    class Client:
        async def post(self, url, json=None):
            calls.append(url)
            if "llama" in url:
                return Resp(521)  # Cloudflare origin dead
            if "publicnode" in url:
                return Resp(body={"error": {"code": -32701,
                           "message": "Please specify an address in your request"}})
            if "cloudflare" in url:
                return Resp(body={"error": {"code": -32046, "message": "Cannot fulfill request"}})
            return Resp(body={"result": "fine"})

    router = RpcFailoverRouter(
        "test",
        ["https://eth.llamarpc.com", "https://arb.publicnode.com",
         "https://cloudflare-eth.com", "https://good.node"],
    )
    router._client = Client()  # type: ignore[assignment]

    assert asyncio.run(router.post({"m": 1})) == "fine"
    # every unhealthy node was skipped; the healthy one answered
    assert set(calls) == {u for u in router._urls if "good" not in u} | {"https://good.node"}

    # cooldown: next call goes straight to the healthy node
    calls.clear()
    assert asyncio.run(router.post({"m": 2})) == "fine"
    assert calls == ["https://good.node"]


def test_solana_address_validation_rejects_corrupt_seed_rows():
    from whaledecode.adapters.chain.solana_poller import is_valid_solana_address

    assert is_valid_solana_address("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2")  # real pubkey
    assert not is_valid_solana_address("0x476c5e26a75bd202a9683ffd34359c0cc15be0ff")  # EVM addr
    assert not is_valid_solana_address("7LMfVrHbP8vWUbsCfdPbZ7PgRB3Y6hB5bTdB8s2zK1")  # WrongSize (31 bytes)
    assert not is_valid_solana_address("not!a@base58#address")

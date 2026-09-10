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
    """Records payloads; serves canned responses; can fail N nodes first.

    Supports both calling conventions:
    - post(payload: dict) — legacy
    - post(chain: str, method: str, params: list) — new explicit interface
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads: list[dict] = []
        self.fail_first = 0

    async def post(self, chain_or_payload, method=None, params=None):
        # Handle both calling conventions
        if isinstance(chain_or_payload, dict):
            payload = chain_or_payload
            self.payloads.append(payload)
            if self.fail_first > 0:
                self.fail_first -= 1
                raise TimeoutError("node down")
            if payload.get("method") == "eth_call":  # decimals()
                return "0x06"  # 6 decimals
            return self.responses.pop(0)
        else:
            # New interface: chain, method, params
            chain = chain_or_payload
            self.payloads.append({"chain": chain, "method": method, "params": params})
            if self.fail_first > 0:
                self.fail_first -= 1
                raise TimeoutError("node down")
            if method == "eth_call":
                return "0x06"
            if method == "getSignaturesForAddress":
                # Respect the 'until' parameter for dedup testing
                until = params[1].get("until") if len(params) > 1 and isinstance(params[1], dict) else None
                if until == "sig1":  # Already seen this signature
                    return []
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
    getlogs = [p for p in router.payloads if p.get("method") == "eth_getLogs"]
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
    # First poll returns 2 signatures, second poll returns only the first (already seen)
    sigs = [{"signature": "sig1", "slot": 100, "err": None},
            {"signature": "sig2", "slot": 99, "err": None}]
    # getTransaction responses for each signature
    tx1 = {
        "meta": {"preBalances": [1000000000], "postBalances": [900000000], "fee": 5000,
                 "preTokenBalances": [], "postTokenBalances": [], "logMessages": []},
        "transaction": {"message": {"accountKeys": [{"pubkey": "9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2"}]}},
        "blockTime": 1234567890, "slot": 100
    }
    tx2 = {
        "meta": {"preBalances": [1000000000], "postBalances": [1100000000], "fee": 5000,
                 "preTokenBalances": [], "postTokenBalances": [], "logMessages": []},
        "transaction": {"message": {"accountKeys": [{"pubkey": "9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2"}]}},
        "blockTime": 1234567900, "slot": 99
    }
    # Response sequence: signatures list, then tx1, then tx2, then signatures list (only sig1), then tx1 again
    router = FakeRouter([sigs, tx1, tx2, [sigs[0]], tx1])
    poller = SolanaTargetedPoller(router)  # type: ignore[arg-type]

    first = await poller.fetch_recent_activity([_wallet("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2", wid=7)])
    second = await poller.fetch_recent_activity([_wallet("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2", wid=7)])

    assert {a["tx_hash"] for a in first} == {"sig1", "sig2"}
    assert second == []  # idempotent re-poll: nothing new
    assert all(a["chain"] == "SOL" for a in first)


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

    assert asyncio.run(router.post({"method": "x"})) == "fine"
    # every unhealthy node was skipped; the healthy one answered
    test_chain = router.pools["test"]
    test_urls = []
    for tier in test_chain.values():
        test_urls.extend(n["url"] for n in tier)
    assert set(calls) == {u for u in test_urls if "good" not in u} | {"https://good.node"}

    # cooldown: next call goes straight to the healthy node
    calls.clear()
    assert asyncio.run(router.post({"method": "y"})) == "fine"
    assert calls == ["https://good.node"]


def test_solana_not_found_errors_dont_penalize_node():
    """RPC -32020 (tx not found) and -32011 (history unavailable) are valid responses,
    not node failures. Router should NOT cooldown the node."""
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
    node_cooldowns = []

    class Client:
        async def post(self, url, json=None):
            calls.append(url)
            method = json.get("method") if json else ""
            if method == "getSignaturesForAddress":
                # First call: -32020 (transaction not found)
                return Resp(body={"error": {"code": -32020, "message": "Transaction ... not found"}})
            elif method == "getTransaction":
                # Second call: -32011 (history unavailable)
                return Resp(body={"error": {"code": -32011, "message": "Transaction history not available"}})
            return Resp(body={"result": "ok"})

    router = RpcFailoverRouter(
        "solana",
        ["https://solana.api.pocket.network"],
    )
    router._client = Client()  # type: ignore[assignment]

    # Track cooldown calls by monkey-patching _penalize_node
    cooldown_count = 0

    def mock_penalize(node, reason):
        nonlocal cooldown_count
        cooldown_count += 1
        node_cooldowns.append((node["name"], reason))

    router._penalize_node = mock_penalize  # type: ignore[assignment]

    # First call - getSignaturesForAddress returns -32020
    # Should raise RuntimeError (all nodes failed) but NOT penalize
    try:
        asyncio.run(router.call("solana", "getSignaturesForAddress", ["addr", {"limit": 1}]))
    except RuntimeError:
        pass
    assert cooldown_count == 0, f"Expected no cooldown for -32020, got: {node_cooldowns}"

    # Second call - getTransaction returns -32011
    try:
        asyncio.run(router.call("solana", "getTransaction", ["sig", {"encoding": "jsonParsed"}]))
    except RuntimeError:
        pass
    assert cooldown_count == 0, f"Expected no cooldown for -32011, got: {node_cooldowns}"


def test_http_500_still_penalizes_node():
    """Real HTTP failures (500, 502, etc.) must still trigger cooldown."""
    import asyncio

    class Resp:
        def __init__(self, status_code=200, body=None):
            self.status_code = status_code
            self._body = body or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    router = RpcFailoverRouter(
        "solana",
        ["https://solana.api.pocket.network", "https://api.mainnet-beta.solana.com"],
    )
    router._client = type("Client", (), {
        "post": lambda self, url, json=None: Resp(status_code=500, body={})
    })()

    # Track cooldown
    cooldown_count = 0
    def mock_penalize(node, reason):
        nonlocal cooldown_count
        cooldown_count += 1

    router._penalize_node = mock_penalize  # type: ignore[assignment]

    try:
        asyncio.run(router.call("solana", "getSignaturesForAddress", ["addr", {"limit": 1}]))
    except RuntimeError:
        pass

    # Each node tried once (no retries in this test setup since max_retries defaults to 5
    # but we're not testing the manager, just the router's single attempt per node)
    assert cooldown_count == 2, f"Both nodes should be penalized for HTTP 500, got {cooldown_count}"
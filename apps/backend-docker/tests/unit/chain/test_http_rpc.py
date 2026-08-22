import json

import eth_abi
import httpx
import pytest
from aiolimiter import AsyncLimiter
from whaledecode.adapters.chain.providers.http_rpc import (
    _TOKEN_METADATA_CACHE,
    ERC20_METADATA_ABI,
    HttpRpcProvider,
    RateLimitError,
)


def _provider(handler: httpx.MockTransport) -> HttpRpcProvider:
    p = HttpRpcProvider({"ETH": "http://x"})
    p._client = httpx.AsyncClient(transport=handler)
    return p


class TestHttpRpcProvider:
    def test_default_headers_applied_to_client(self) -> None:
        p = HttpRpcProvider({"ETH": "http://x"})
        headers = p._client.headers
        assert headers["user-agent"] == "WhaleDecodeBot/1.0"
        assert headers["accept"] == "application/json"
        assert headers["content-type"] == "application/json"

    def test_chain_names_normalized_to_codes(self) -> None:
        p = HttpRpcProvider({"ETH": "http://eth", "ARB": "http://arb", "BASE": "http://base"})
        assert p._url_for_chain("Ethereum") == "http://eth"
        assert p._url_for_chain("ethereum") == "http://eth"
        assert p._url_for_chain("ETH") == "http://eth"
        assert p._url_for_chain("Arbitrum") == "http://arb"
        assert p._url_for_chain("arb") == "http://arb"
        assert p._url_for_chain("Base") == "http://base"
        assert p._url_for_chain("base") == "http://base"

    def test_unknown_chain_raises(self) -> None:
        p = HttpRpcProvider({"ETH": "http://x"})
        with pytest.raises(ValueError, match="Unsupported chain"):
            p._url_for_chain("Solana")

    async def test_non_200_response_raises_value_error_with_body(self, capsys: pytest.CaptureFixture[str]) -> None:
        p = _provider(httpx.MockTransport(lambda r: httpx.Response(403, text="<html>challenge</html>")))
        with pytest.raises(ValueError, match="<html>challenge</html>"):
            await HttpRpcProvider.rpc_call.__wrapped__(p, "eth_blockNumber")
        out = capsys.readouterr().out
        assert "rpc_invalid_response" in out
        assert "<html>challenge</html>" in out

    async def test_non_json_200_response_raises_value_error_with_body(self, capsys: pytest.CaptureFixture[str]) -> None:
        p = _provider(httpx.MockTransport(lambda r: httpx.Response(200, text="<html>WAF</html>")))
        with pytest.raises(ValueError, match="<html>WAF</html>"):
            await HttpRpcProvider.rpc_call.__wrapped__(p, "eth_blockNumber")
        out = capsys.readouterr().out
        assert "rpc_invalid_response" in out
        assert "<html>WAF</html>" in out

    async def test_get_logs_payload_includes_addresses(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": []})

        p = _provider(httpx.MockTransport(handler))
        await p.get_logs(chain="ETH", addresses=["0xabc", "0xdef"], from_block=1, to_block=2)
        params = captured["payload"]["params"][0]
        assert params["address"] == ["0xabc", "0xdef"]
        assert int(params["fromBlock"], 16) == 1
        assert int(params["toBlock"], 16) == 2

    async def test_rpc_call_waits_for_limiter_capacity(self) -> None:
        acquired = []

        def handler(request: httpx.Request) -> httpx.Response:
            acquired.append("http")
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x1"})

        p = _provider(httpx.MockTransport(handler))
        p._limiter = AsyncLimiter(max_rate=1000, time_period=60)

        await p.rpc_call.__wrapped__(p, "eth_blockNumber")
        await p.rpc_call.__wrapped__(p, "eth_blockNumber")

        assert len(acquired) == 2

    async def test_rate_limit_wait_times_out_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x1"})

        p = _provider(httpx.MockTransport(handler))
        p._limiter = AsyncLimiter(max_rate=1, time_period=60)
        await p._limiter.acquire()  # exhaust the only token
        p._rate_limit_wait = 0.05

        with pytest.raises(RateLimitError):
            await p.rpc_call.__wrapped__(p, "eth_blockNumber")

    async def test_token_metadata_cached_across_calls(self) -> None:
        _TOKEN_METADATA_CACHE.clear()
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            data = json.loads(request.content)["params"][0]["data"]
            if data == ERC20_METADATA_ABI["name"]:
                result = eth_abi.encode(["string"], ["USD Coin"])
            elif data == ERC20_METADATA_ABI["symbol"]:
                result = eth_abi.encode(["string"], ["USDC"])
            else:
                result = eth_abi.encode(["uint256"], [6])
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x" + result.hex()})

        p = _provider(httpx.MockTransport(handler))
        token = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

        first = await p.get_token_metadata("ETH", token)
        second = await p.get_token_metadata("ETH", token)

        assert first == second == {"name": "USD Coin", "symbol": "USDC", "decimals": 6, "address": token}
        assert request_count == 3  # second lookup served entirely from cache

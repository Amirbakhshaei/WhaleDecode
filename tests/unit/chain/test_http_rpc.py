import httpx
import pytest
from whaledecode.adapters.chain.providers.http_rpc import HttpRpcProvider


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

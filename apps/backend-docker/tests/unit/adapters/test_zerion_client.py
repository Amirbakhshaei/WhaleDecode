"""Zerion cold-start fallback client (Module 1 Option B)."""
import httpx
import pytest
import respx
from whaledecode.adapters.zerion.client import ZerionClient


@respx.mock
@pytest.mark.asyncio
async def test_snapshot_parses_pnl():
    respx.get("https://api.zerion.io/v1/wallets/0xabc/pnl").respond(
        json={"data": {"attributes": {"realized_pnl": "1200.5", "unrealized_pnl": 300}}}
    )
    snap = await ZerionClient(api_key="k").wallet_snapshot("base", "0xABC")
    assert snap["pnl_usd"] == pytest.approx(1500.5)


@respx.mock
@pytest.mark.asyncio
async def test_snapshot_fail_soft_on_http_error():
    respx.get("https://api.zerion.io/v1/wallets/0xdead/pnl").mock(return_value=httpx.Response(500))
    assert await ZerionClient(api_key="k").wallet_snapshot("base", "0xdead") == {}


@pytest.mark.asyncio
async def test_no_key_or_unsupported_chain_short_circuits():
    assert await ZerionClient(api_key="").wallet_snapshot("base", "0xa") == {}
    assert await ZerionClient(api_key="k").wallet_snapshot("sui", "0xa") == {}

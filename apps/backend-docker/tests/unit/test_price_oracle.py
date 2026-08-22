import time

import pytest
import respx
from httpx import Response
from whaledecode.adapters.pricing.oracle import (
    COINGECKO_LIST_URL,
    COINGECKO_OHLC_URL,
    DEFILLAMA_PRICE_URL,
    PriceOracle,
)

CONTRACT = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
COIN_ID = "usd-coin"

_PRICE_BODY = {
    "coins": {
        f"ethereum:{CONTRACT}": {
            "decimals": 6,
            "symbol": "SHIB",
            "price": 0.00003,
            "timestamp": 1786448570,
            "confidence": 0.99,
        }
    }
}

# 180 x 4h candles: price ramps 1.00 → 1.20 so buckets differ.
_CANDLES = [
    [
        1786233600000 + i * 4 * 3600 * 1000,
        1.0 + i * 0.001,
        1.0 + i * 0.001 + 0.001,
        1.0 + i * 0.001,
        1.0 + i * 0.001 + 0.0005,
    ]
    for i in range(180)
]


@respx.mock
async def test_get_token_symbol_captured_from_price_response() -> None:
    _mock_endpoints()
    oracle = PriceOracle()
    assert await oracle.get_token_symbol(CONTRACT, "ethereum") == "SHIB"


@respx.mock
async def test_get_price_usd_at_recent_timestamp_reuses_current_price() -> None:
    _mock_endpoints()
    oracle = PriceOracle()
    price = await oracle.get_token_price_usd_at(CONTRACT, "ethereum", time.time())
    assert price == pytest.approx(0.00003)


@respx.mock
async def test_get_price_usd_at_old_timestamp_hits_historical() -> None:
    old_ts = int(time.time()) - 86400
    respx.get(f"https://coins.llama.fi/prices/historical/{old_ts}/ethereum:{CONTRACT}").mock(
        return_value=Response(200, json={"coins": {f"ethereum:{CONTRACT}": {"price": 0.5}}})
    )
    _mock_endpoints()
    oracle = PriceOracle()
    assert await oracle.get_token_price_usd_at(CONTRACT, "ethereum", old_ts) == pytest.approx(0.5)


@respx.mock
async def test_get_price_levels_derives_24h_7d_30d() -> None:
    _mock_endpoints()
    oracle = PriceOracle()
    levels = await oracle.get_price_levels(CONTRACT, "ethereum")
    assert levels["24h"]["low"] < levels["24h"]["high"]
    assert levels["7d"]["low"] < levels["24h"]["low"]  # larger window → lower min
    assert levels["30d"]["low"] < levels["7d"]["low"]
    assert len(levels["daily_closes"]) == 5


@respx.mock
async def test_get_price_levels_empty_on_failure() -> None:
    _mock_endpoints()
    respx.get(COINGECKO_OHLC_URL.format(coin_id=COIN_ID)).mock(return_value=Response(500))
    oracle = PriceOracle()
    assert await oracle.get_price_levels(CONTRACT, "ethereum") == {}


@respx.mock
async def test_get_token_price_usd_returns_zero_on_unknown_chain() -> None:
    _mock_endpoints()
    oracle = PriceOracle()
    assert await oracle.get_token_price_usd(CONTRACT, "not-a-chain") == 0.0


def _mock_endpoints() -> None:
    respx.get(DEFILLAMA_PRICE_URL.format(chain_id="ethereum", contract_address=CONTRACT)).mock(
        return_value=Response(200, json=_PRICE_BODY)
    )
    respx.get(COINGECKO_LIST_URL).mock(
        return_value=Response(200, json=[{"id": COIN_ID, "symbol": "usdc", "name": "USDC", "platforms": {"ethereum": CONTRACT}}])
    )
    respx.get(COINGECKO_OHLC_URL.format(coin_id=COIN_ID)).mock(return_value=Response(200, json=_CANDLES))

"""DexScreener TTL cache: repeat lookups for the same token skip the network."""
import httpx
from whaledecode.adapters.llm_graph.tools.data_gatherer_tools import (
    _DEXSCREENER_CACHE,
    create_data_gatherer_tools,
)

TOKEN = "0x" + "a" * 40


def _dex_response() -> dict:
    return {
        "pairs": [
            {
                "chainId": "ethereum",
                "priceUsd": "1.23",
                "liquidity": {"usd": 1000},
                "volume": {"h24": 500},
                "pairAddress": "0xpair",
            }
        ]
    }


async def test_dexscreener_second_call_uses_cache() -> None:
    calls: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_dex_response())

    tools = create_data_gatherer_tools(object(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    dexscreener = next(t for t in tools if t.name == "dexscreener_tool")

    _DEXSCREENER_CACHE.clear()
    first = await dexscreener.ainvoke({"token_address": TOKEN, "chain": "ETH"})
    second = await dexscreener.ainvoke({"token_address": TOKEN, "chain": "ETH"})

    assert first == second
    assert len(calls) == 1, "second lookup should hit the TTL cache, not the network"

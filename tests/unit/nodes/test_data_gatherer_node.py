import httpx
import pytest
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.adapters.llm_graph.nodes.data_gatherer_node import enrich_event_context


def _http_client(payload: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_enrich_resolves_curated_labels_from_db(session_factory) -> None:
    async with session_factory() as session:
        session.add(CuratedWalletModel(address="0xabc", chain="ETH", label="Binance 16"))
        session.add(CuratedWalletModel(address="0xdef", chain="ETH", label="Wintermute MM"))
        await session.commit()

    enriched = await enrich_event_context(
        from_addr="0xABC", to_addr="0xdef", token_addr=None, chain="ETH", session_factory=session_factory
    )

    assert enriched["from_label"] == "Binance 16"
    assert enriched["to_label"] == "Wintermute MM"


@pytest.mark.asyncio
async def test_enrich_defaults_to_unlabeled_when_not_curated(session_factory) -> None:
    async with session_factory() as session:
        session.add(CuratedWalletModel(address="0xabc", chain="ETH", label="Binance 16"))
        await session.commit()

    enriched = await enrich_event_context(
        from_addr="0x999", to_addr="0xdef", token_addr=None, chain="ETH", session_factory=session_factory
    )

    assert enriched["from_label"] == "Unlabeled Entity"
    assert enriched["to_label"] == "Unlabeled EOA"


@pytest.mark.asyncio
async def test_enrich_skips_db_when_no_session_factory() -> None:
    enriched = await enrich_event_context(
        from_addr="0xabc", to_addr="0xdef", token_addr=None, chain="ETH", session_factory=None
    )
    assert enriched["from_label"] == "Unlabeled Entity"
    assert enriched["to_label"] == "Unlabeled EOA"


@pytest.mark.asyncio
async def test_enrich_fills_dex_metrics_from_dexscreener() -> None:
    client = _http_client(
        {
            "pairs": [
                {
                    "chainId": "ethereum",
                    "liquidity": {"usd": 2_500_000},
                    "priceChange": {"h24": 3.21},
                }
            ]
        }
    )

    enriched = await enrich_event_context(
        from_addr="0xabc", to_addr="0xdef", token_addr="0x" + "b" * 40, chain="ETH", http_client=client
    )

    assert enriched["pool_liquidity_usd"] == 2_500_000
    assert enriched["token_24h_change"] == 3.21


@pytest.mark.asyncio
async def test_enrich_degrades_gracefully_on_dexscreener_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    enriched = await enrich_event_context(
        from_addr="0xabc", to_addr="0xdef", token_addr="0x" + "b" * 40, chain="ETH", http_client=client
    )

    assert enriched["pool_liquidity_usd"] is None
    assert enriched["token_24h_change"] is None

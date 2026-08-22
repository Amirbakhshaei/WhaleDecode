"""Tests for webhook pruning and webhook-eligibility gating."""
import json

import httpx
import pytest
from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager
from whaledecode.adapters.curation import CuratedSeed, is_webhook_eligible
from whaledecode.cli.prune_alchemy_webhooks import BLACKLISTED_ADDRESSES


def _client(mocker, handler):
    real_client = httpx.AsyncClient
    mocker.patch.object(httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=handler))


@pytest.mark.asyncio
async def test_list_addresses_paginates_and_lowercases(mocker):
    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": ["0xABC", "0xDEF"],
                "pagination": {"next": "https://dashboard.alchemy.com/api/webhook-addresses?page=2"},
            }
            if "page=2" not in str(request.url)
            else {"data": ["0x123"], "pagination": {}},
        )
    )
    _client(mocker, handler)
    manager = AlchemyWebhookManager(alchemy_auth_token="t", webhook_ids={"ETH": "wh_eth"})
    assert await manager.list_addresses("wh_eth") == ["0xabc", "0xdef", "0x123"]


@pytest.mark.asyncio
async def test_remove_addresses_patches_with_remove_list(mocker):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, json.loads(request.content)))
        return httpx.Response(200, json={})

    _client(mocker, httpx.MockTransport(handler))
    manager = AlchemyWebhookManager(alchemy_auth_token="t", webhook_ids={"ETH": "wh_eth"})
    ok = await manager.remove_addresses("wh_eth", ["0xabc", "0xdef"])
    assert ok is True
    assert calls == [("PATCH", {"webhook_id": "wh_eth", "addresses_to_add": [], "addresses_to_remove": ["0xabc", "0xdef"]})]


def test_is_webhook_eligible_gate():
    whale = CuratedSeed("0x" + "a" * 40, "ETH", "EVM", "w", "Notable Whale", quality_score=90.0)
    assert is_webhook_eligible(whale) is True
    low_score = CuratedSeed("0x" + "a" * 40, "ETH", "EVM", "w", "Notable Whale", quality_score=80.0)
    assert is_webhook_eligible(low_score) is False
    dex = CuratedSeed("0x" + "a" * 40, "ETH", "EVM", "w", "DEX", quality_score=95.0)
    assert is_webhook_eligible(dex) is False


def test_is_safe_for_webhook_sync_drops_blacklisted():
    from whaledecode.adapters.curation import DISALLOWED_WEBHOOK_ADDRESSES, is_safe_for_webhook_sync

    usdt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
    uniswap_router = "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad"

    # Blacklisted regardless of category/score.
    assert usdt in DISALLOWED_WEBHOOK_ADDRESSES
    assert uniswap_router in DISALLOWED_WEBHOOK_ADDRESSES
    assert is_safe_for_webhook_sync({"address": usdt, "category": "Notable Whale", "quality_score": 99.0}) is False
    assert is_safe_for_webhook_sync({"address": uniswap_router, "category": "Notable Whale", "quality_score": 99.0}) is False

    # High-conviction, non-blacklisted passes.
    assert is_safe_for_webhook_sync({"address": "0x" + "a" * 40, "category": "Notable Whale", "quality_score": 90.0}) is True
    # Address comparison is case-insensitive.
    assert is_safe_for_webhook_sync({"address": usdt.upper(), "category": "Notable Whale", "quality_score": 99.0}) is False


@pytest.mark.asyncio
async def test_run_pruner_removes_blacklisted(mocker):
    import whaledecode.cli.prune_alchemy_webhooks as pruner_mod
    from whaledecode.adapters.alchemy import webhook_manager as wm

    blacklisted = next(iter(BLACKLISTED_ADDRESSES))

    # One webhook contains a blacklisted token contract; ARB is clean; BASE unconfigured.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/webhook-addresses":
            wid = request.url.params.get("webhook_id")
            data = [blacklisted] if wid == "wh_eth" else []
            return httpx.Response(200, json={"data": data, "pagination": {}})
        return httpx.Response(200, json={})

    fake_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    mocker.patch.object(wm.HttpClientManager, "get_client", return_value=fake_client)
    manager = AlchemyWebhookManager(alchemy_auth_token="t", webhook_ids={"ETH": "wh_eth", "ARB": "wh_arb", "BASE": ""})
    mocker.patch.object(pruner_mod.AlchemyWebhookManager, "from_settings", return_value=manager)

    assert await pruner_mod.run_pruner() == 0

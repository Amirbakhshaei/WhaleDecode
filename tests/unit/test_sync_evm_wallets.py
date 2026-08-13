import asyncio
import json

import httpx
import pytest
from sqlalchemy import select
from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.cli.sync_evm_wallets import _CHAINS, _collect_evm_addresses, _ensure_all_chains

A = "0xaa" + "1" * 38
B = "0xbb" + "2" * 38


@pytest.mark.asyncio
async def test_collect_evm_addresses_filters_non_hex(db_session):
    db_session.add(CuratedWalletModel(address=A, chain="ETH", is_active=True))
    db_session.add(CuratedWalletModel(address=A, chain="ARB", is_active=True))
    db_session.add(CuratedWalletModel(address=B, chain="BASE", is_active=True))
    db_session.add(CuratedWalletModel(address="not-an-evm", chain="ETH", is_active=True))
    await db_session.commit()

    assert await _collect_evm_addresses(db_session) == sorted([A, B])


@pytest.mark.asyncio
async def test_ensure_all_chains_inserts_missing_and_is_idempotent(db_session):
    db_session.add(CuratedWalletModel(address=A, chain="ETH", is_active=True))
    db_session.add(CuratedWalletModel(address=B, chain="BASE", is_active=True))
    await db_session.commit()

    addresses = await _collect_evm_addresses(db_session)
    inserted = await _ensure_all_chains(db_session, addresses)
    await db_session.commit()

    expected = {(a, c) for a in addresses for c in _CHAINS}
    rows = set((r.address, r.chain) for r in (await db_session.execute(select(CuratedWalletModel))).scalars())
    assert rows == expected
    assert inserted == (len(_CHAINS) - 1) * len(addresses)

    again = await _ensure_all_chains(db_session, addresses)
    assert again == 0


@pytest.mark.asyncio
async def test_ensure_all_chains_inserts_active_rows(db_session):
    db_session.add(CuratedWalletModel(address=A, chain="ETH", is_active=True))
    await db_session.commit()

    await _ensure_all_chains(db_session, [A])
    await db_session.commit()

    rows = (await db_session.execute(select(CuratedWalletModel))).scalars().all()
    assert all(row.is_active for row in rows)
    assert {row.chain for row in rows if row.address == A} == set(_CHAINS)


def test_sync_addresses_patches_each_chain(mocker):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, json.loads(request.content)))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    mocker.patch.object(httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=transport))

    manager = AlchemyWebhookManager(
        alchemy_auth_token="secret",
        webhook_ids={"ETH": "wh_eth", "ARB": "wh_arb", "BASE": "wh_base"},
    )
    asyncio.run(manager.sync_addresses([A, B]))

    assert len(calls) == 3
    for method, payload in calls:
        assert method == "PATCH"
        assert payload["addresses_to_remove"] == []
        assert payload["addresses_to_add"] == [A, B]
    assert {p["webhook_id"] for _, p in calls} == {"wh_eth", "wh_arb", "wh_base"}


def test_sync_addresses_skips_unconfigured_webhook(mocker):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    mocker.patch.object(httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=transport))

    manager = AlchemyWebhookManager(alchemy_auth_token="secret", webhook_ids={"ETH": "wh_eth", "ARB": ""})
    asyncio.run(manager.sync_addresses([A]))

    assert calls == ["/api/update-webhook-addresses"]


def test_from_settings_maps_webhook_ids(mocker):
    settings = mocker.Mock()
    settings.ALCHEMY_NOTIFY_TOKEN = mocker.Mock()
    settings.ALCHEMY_NOTIFY_TOKEN.get_secret_value.return_value = "token"
    settings.ALCHEMY_WEBHOOK_ID_ETH = "wh_eth"
    settings.ALCHEMY_WEBHOOK_ID_ARB = "wh_arb"
    settings.ALCHEMY_WEBHOOK_ID_BASE = "wh_base"

    manager = AlchemyWebhookManager.from_settings(settings)
    assert manager.auth_token == "token"
    assert manager.webhook_ids == {"ETH": "wh_eth", "ARB": "wh_arb", "BASE": "wh_base"}

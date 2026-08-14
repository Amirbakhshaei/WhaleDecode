import httpx
import pytest

from whaledecode.adapters.curation.sources import (
    CuratedSeed,
    DefiLlamaAdapter,
    DuneApiAdapter,
    DuneSpellbookAdapter,
    validate_seed,
)


def _dune_transport(execute_status=200, execution_status=200, state="QUERY_STATE_COMPLETED", rows=None):
    if rows is None:
        rows = [{"address": "0x" + "a" * 40, "name": "Acme", "chain": "ethereum", "label_type": "cex"}]

    def handler(request):
        if request.url.path.endswith("/sql/execute"):
            return httpx.Response(execute_status, json={"execution_id": "exec123"})
        if request.url.path.endswith("/status"):
            return httpx.Response(execution_status, json={"state": state})
        if request.url.path.endswith("/results"):
            return httpx.Response(200, json={"state": state, "result": {"rows": rows}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _transport(protocols_payload):
    def handler(request):
        if request.url.path.endswith("/treasuries"):
            return httpx.Response(402, json={"error": "upgrade to paid plan"})
        if request.url.path.endswith("/protocols"):
            return httpx.Response(200, json=protocols_payload)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_dune_baseline_yields_valid_seeds():
    seeds = await DuneSpellbookAdapter().fetch()
    assert len(seeds) >= 10
    for s in seeds:
        validate_seed(s)  # must not raise


@pytest.mark.asyncio
async def test_dune_has_evm_and_solana():
    seeds = await DuneSpellbookAdapter().fetch()
    families = {s.network_family for s in seeds}
    assert "EVM" in families and "SVM" in families


@pytest.mark.asyncio
async def test_defillama_paywalled_treasuries_still_reads_protocols():
    payload = [{"name": "Acme", "address": "0x" + "a" * 40, "chain": "Ethereum"}]
    client = httpx.AsyncClient(transport=_transport(payload))
    seeds = await DefiLlamaAdapter(client=client).fetch()
    await client.aclose()
    assert any(s.address == "0x" + "a" * 40 for s in seeds)


@pytest.mark.asyncio
async def test_defillama_no_addresses_yields_empty():
    client = httpx.AsyncClient(transport=_transport([{"name": "Acme", "chain": "Ethereum"}]))
    seeds = await DefiLlamaAdapter(client=client).fetch()
    await client.aclose()
    assert seeds == []


def test_validate_seed_rejects_bad_evm():
    with pytest.raises(ValueError):
        validate_seed(CuratedSeed(address="0x123", chain="ETH", network_family="EVM", label="x"))


def test_validate_seed_rejects_bad_solana():
    with pytest.raises(ValueError):
        validate_seed(CuratedSeed(address="0x123", chain="SOL", network_family="SVM", label="x"))


@pytest.mark.asyncio
async def test_dune_api_success_returns_seeds():
    client = httpx.AsyncClient(transport=_dune_transport())
    seeds = await DuneApiAdapter(api_key="k", client=client).fetch()
    await client.aclose()
    assert len(seeds) == 1
    assert seeds[0].address == "0x" + "a" * 40
    assert seeds[0].chain == "ETH"
    assert seeds[0].tags == ("dune",)


@pytest.mark.asyncio
async def test_dune_api_quota_returns_empty():
    client = httpx.AsyncClient(transport=_dune_transport(execute_status=429))
    seeds = await DuneApiAdapter(api_key="k", client=client).fetch()
    await client.aclose()
    assert seeds == []


@pytest.mark.asyncio
async def test_dune_api_poll_quota_returns_empty():
    client = httpx.AsyncClient(transport=_dune_transport(execution_status=429))
    seeds = await DuneApiAdapter(api_key="k", client=client).fetch()
    await client.aclose()
    assert seeds == []


@pytest.mark.asyncio
async def test_dune_api_skips_non_evm():
    client = httpx.AsyncClient(
        transport=_dune_transport(rows=[{"address": "nothex", "chain": "ethereum", "name": "X"}])
    )
    seeds = await DuneApiAdapter(api_key="k", client=client).fetch()
    await client.aclose()
    assert seeds == []

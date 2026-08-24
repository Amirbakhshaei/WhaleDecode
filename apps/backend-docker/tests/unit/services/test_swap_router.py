"""Module 4: swap deep-link router."""
from whaledecode.services.swap_router import build_swap_links


def test_builds_three_buttons_with_fee_params_for_base():
    links = build_swap_links("base", "0xToken", fee_recipient="0xFEE", fee_bps=80)
    assert list(links) == ["⚡ Buy 0.1 ETH", "⚡ Buy 0.5 ETH", "⚡ Custom Swap"]
    for url in links.values():
        assert "matcha.xyz/swap/base?sellToken=ETH&buyToken=0xToken" in url
        if "feeBps" in url:
            assert "feeBps=80" in url and "affiliateAddress=0xFEE" in url


def test_arbitrum_slug_and_no_recipient_omits_fee():
    links = build_swap_links("arbitrum", "0xABC")
    assert all("/swap/arbitrum?" in u for u in links.values())
    assert all("affiliateAddress" not in u and "feeBps" not in u for u in links.values())


def test_empty_token_returns_empty():
    assert build_swap_links("base", "") == {}


def test_solana_routes_to_jupiter():
    links = build_swap_links("sol", "So11111111111111111111111111111111")
    assert all(u.startswith("https://jup.ag/swap/SOL-") for u in links.values())
    assert all("referrer=whaledecode" in u for u in links.values())

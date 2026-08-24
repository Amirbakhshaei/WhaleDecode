"""In-Bot 1-Click DEX Routing (Module 4).

Two layers:
* Deterministic deep-links (no I/O, used on the alert keyboard): execution
  happens on Matcha — 0x's consumer app — with WhaleDecode's affiliate fee
  parameters in the URL. Non-custodial, zero server-side latency.
* On-demand 0x Swap API v2 quotes (``ZeroXClient``) when a user actually taps
  a swap flow inside the bot: deterministic rate + fee preview before they
  execute.
"""
from urllib.parse import quote_plus

DEFAULT_FEE_BPS = 80  # 0.8% protocol value capture


def _chain_slug(chain: str) -> str:
    c = chain.strip().lower()
    if c in ("base", "8453"):
        return "base"
    if c in ("arbitrum", "arb", "42161"):
        return "arbitrum"
    if c in ("sol", "solana"):
        return "sol"
    return "ethereum"


PRESETS = [0.1, 0.5]


def build_swap_links(
    chain: str,
    token_address: str,
    *,
    fee_recipient: str = "",
    fee_bps: int = DEFAULT_FEE_BPS,
) -> dict[str, str]:
    """Return {label: url} one-click buy buttons for a token purchase alert.

    EVM chains route through Matcha (0x v2 frontend) carrying the affiliate
    fee params; Solana falls back to Jupiter. Empty ``token_address`` → {}.
    """
    token_address = (token_address or "").strip()
    if not token_address:
        return {}
    slug = _chain_slug(chain)
    if slug == "sol":
        base = (
            f"https://jup.ag/swap/SOL-{quote_plus(token_address)}"
            "?referrer=whaledecode"
        )
        return {
            "⚡ Buy 0.1 SOL": base,
            "⚡ Buy 0.5 SOL": base,
            "⚡ Custom Swap": base,
        }
    native = {"ethereum": "ETH", "base": "ETH", "arbitrum": "ETH"}[slug]
    # Fee capture requires a registered recipient; without one the link is
    # fee-free rather than mis-attributed.
    fee_qs = (
        f"feeBps={fee_bps}&affiliateAddress={quote_plus(fee_recipient)}"
        if fee_recipient
        else ""
    )

    def _matcha(amount: float | None) -> str:
        url = f"https://matcha.xyz/swap/{slug}?sellToken={native}&buyToken={quote_plus(token_address)}"
        if amount is not None:
            url += f"&sellAmount={amount}"
        return f"{url}&{fee_qs}" if fee_qs else url

    links = {f"⚡ Buy {amount} {native}": _matcha(amount) for amount in PRESETS}
    links["⚡ Custom Swap"] = _matcha(None)
    return links

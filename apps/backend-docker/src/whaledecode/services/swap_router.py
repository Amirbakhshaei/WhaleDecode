"""In-Bot 1-Click DEX Routing via aggregator deep-links (Module 4).

Non-custodial: we only build URLs. The user's browser/wallet opens the
aggregator with WhaleDecode's fee parameters baked in — no keys, no gas
sponsorship, no swap infrastructure to operate.

Fee capture:
* 1inch (EVM): ``fee=<bps>`` + ``referrer=<address>`` query params.
* Jupiter (Solana): fee taken via platform fee account; configured at the
  Jupiter dashboard level, so the link just needs the t.me referrer marker.
"""
from urllib.parse import quote_plus

# ponytail: single flat fee for all aggregators; per-chain fee overrides if
# finance ever wants them.
DEFAULT_FEE_BPS = 80  # 0.8%


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

    EVM chains route through 1inch Classic swap with affiliate fee params;
    Solana falls back to Jupiter. Empty ``token_address`` yields {} (no button).
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
    params = f"referrer={quote_plus(fee_recipient)}&fee={fee_bps}" if fee_recipient else ""
    sep = "&" if params else ""

    def _oneinch(amount: float) -> str:
        return (
            f"https://app.1inch.io/#{slug}/swap/{native}/{token_address}"
            f"?amount={amount}{sep}{params}"
        )

    links = {f"⚡ Buy {amount} {native}": _oneinch(amount) for amount in PRESETS}
    links["⚡ Custom Swap"] = _oneinch(1.0).split("?")[0] + ("?" + params if params else "")
    return links

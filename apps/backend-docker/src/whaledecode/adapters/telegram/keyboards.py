from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from whaledecode.config.settings import Settings

# Short chain code -> explorer base URL (tx view).
_EXPLORER_BASE = {
    "ETH": "https://etherscan.io/tx/",
    "ARB": "https://arbiscan.io/tx/",
    "BASE": "https://basescan.org/tx/",
    "SOL": "https://solscan.io/tx/",
}

# Short chain code -> explorer base URL (address view).
_EXPLORER_ADDR_BASE = {
    "ETH": "https://etherscan.io/address/",
    "ARB": "https://arbiscan.io/address/",
    "BASE": "https://basescan.org/address/",
    "SOL": "https://solscan.io/account/",
}

# Canonical chain label/name/id -> short code.
_CHAIN_CODE = {
    "ethereum": "ETH", "eth": "ETH", "1": "ETH",
    "arbitrum": "ARB", "arb": "ARB", "42161": "ARB",
    "base": "BASE", "8453": "BASE",
    "solana": "SOL", "sol": "SOL",
}


def _chain_code(chain: str) -> str:
    return _CHAIN_CODE.get(str(chain).strip().lower(), "ETH")


def explorer_tx_url(chain: str, tx_hash: str) -> str:
    code = _chain_code(chain)
    return f"{_EXPLORER_BASE.get(code, _EXPLORER_BASE['ETH'])}{tx_hash}"


def explorer_address_url(chain: str, address: str) -> str:
    code = _chain_code(chain)
    return f"{_EXPLORER_ADDR_BASE.get(code, _EXPLORER_ADDR_BASE['ETH'])}{address}"


def _bot_deep_link(action: str, chain: str, ref: str) -> str:
    """t.me deep link back into /start with a routed payload."""
    bot = Settings().BOT_USERNAME.strip().lstrip("@")
    code = _chain_code(chain)
    return f"https://t.me/{bot}?start={action}_{code}_{ref}"


def build_tx_action_hub(
    chain: str,
    tx_hash: str,
    event_id: int | None = None,
    from_addr: str = "",
    token_address: str = "",
) -> InlineKeyboardMarkup:
    """Full intelligence suite shown in the private chat for a ``tx_`` deep link.

    All tx-bound links reference candidate_events by id — Telegram caps
    ``?start=`` payloads at 64 bytes and a raw hash exceeds that. Entity
    Dossier and Mirror Trade reuse the existing wallet_/swap_ deep links
    (addresses fit within the limit). Explorer stays in-chat, never on the
    public channel.
    """
    ref = str(event_id) if event_id else tx_hash
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="💬 Ask AI About This", url=_bot_deep_link("analyze", chain, ref))],
    ]
    if (from_addr or "").strip():
        rows.append([
            InlineKeyboardButton(text="📊 View Entity Dossier", url=_bot_deep_link("wallet", chain, from_addr.strip())),
        ])
    if (token_address or "").strip():
        rows.append([
            InlineKeyboardButton(text="🛒 1-Click Mirror Trade", url=_bot_deep_link("swap", chain, token_address.strip())),
        ])
    rows.append([InlineKeyboardButton(text="🔍 Block Explorer", url=explorer_tx_url(chain, tx_hash))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_wallet_dossier_hub(chain: str, wallet: str) -> InlineKeyboardMarkup:
    """Inline menu shown in the private chat for a ``wallet_`` deep link.

    Address-bound actions fit comfortably in callback_data (<=64 bytes).
    """
    code = _chain_code(chain)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔔 Track / Untrack Wallet", callback_data=f"act:track:{code}:{wallet}"),
                InlineKeyboardButton(text="💼 Portfolio Breakdown", callback_data=f"act:port:{code}:{wallet}"),
            ],
            [
                InlineKeyboardButton(text="💬 Ask AI About Wallet", callback_data=f"act:chatw:{code}:{wallet}"),
                InlineKeyboardButton(text="🔍 View on Explorer", url=explorer_address_url(chain, wallet)),
            ],
        ]
    )


def get_channel_alert_keyboard(
    chain: str,
    tx_hash: str,
    from_addr: str = "",
    bot_username: str = "",
    token_address: str = "",
    event_id: int = 0,
) -> InlineKeyboardMarkup:
    """Single high-contrast CTA for public channel broadcasts.

    The channel is purely top-of-funnel: one button deep-links into the
    private bot, which renders the full action suite. The hub link carries
    the candidate_events id, not the hash — Telegram drops ``?start=``
    payloads over 64 bytes and a full tx hash exceeds that.
    """
    bot = (bot_username or Settings().BOT_USERNAME).strip().lstrip("@") or "whaledecodebot"
    code = _chain_code(chain)
    hub_ref = str(event_id) if event_id else tx_hash
    hub_url = f"https://t.me/{bot}?start=tx_{code}_{hub_ref}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⚡ Open Intelligence Hub", url=hub_url)]]
    )

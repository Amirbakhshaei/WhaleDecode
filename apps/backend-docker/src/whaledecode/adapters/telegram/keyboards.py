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


def build_tx_action_hub(chain: str, tx_hash: str) -> InlineKeyboardMarkup:
    """Inline menu shown in the private chat for a ``tx_`` deep link.

    Tx-hash-bound actions are URL deep links (a 66-char hash exceeds
    callback_data's 64-byte limit) re-entering /start with the legacy
    immediate-action prefixes.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔬 Run Full Deep Dive", url=_bot_deep_link("analyze", chain, tx_hash)),
                InlineKeyboardButton(text="💬 Ask AI About This Tx", url=_bot_deep_link("ask", chain, tx_hash)),
            ],
            [
                InlineKeyboardButton(text="📊 Counterparty Network", url=_bot_deep_link("net", chain, tx_hash)),
                InlineKeyboardButton(text="🔍 Block Explorer", url=explorer_tx_url(chain, tx_hash)),
            ],
        ]
    )


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
    from_addr: str,
    bot_username: str = "",
    token_address: str = "",
) -> InlineKeyboardMarkup:
    """Parameterized inline keyboard for public channel broadcasts (Phase 3 spec).

    Strictly URL deep links into @WhaleDecodeBot (callback_data is forbidden on
    public channel messages): Intelligence Hub, 1-Click Swap, Track Cluster,
    and the on-chain graph explorer view.
    """
    bot = (bot_username or Settings().BOT_USERNAME).strip().lstrip("@") or "whaledecodebot"
    code = _chain_code(chain)
    hub_url = f"https://t.me/{bot}?start=tx_{code}_{tx_hash}"
    cluster_url = f"https://t.me/{bot}?start=wallet_{code}_{from_addr}"
    explorer_url = explorer_tx_url(chain, tx_hash)

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⚡ Open Intelligence Hub", url=hub_url)],
        [
            InlineKeyboardButton(text="🕵️ Track Cluster", url=cluster_url),
            InlineKeyboardButton(text="🔍 View Graph", url=explorer_url),
        ],
    ]
    if (token_address or "").strip():
        swap_url = f"https://t.me/{bot}?start=swap_{token_address.strip()}"
        # Spec order: swap row sits directly under the hub.
        rows.insert(1, [InlineKeyboardButton(text="🛒 1-Click Swap", url=swap_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

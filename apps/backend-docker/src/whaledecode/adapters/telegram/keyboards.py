from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from whaledecode.config.settings import Settings

# Short chain code -> explorer base URL (tx view).
_EXPLORER_BASE = {
    "ETH": "https://etherscan.io/tx/",
    "ARB": "https://arbiscan.io/tx/",
    "BASE": "https://basescan.org/tx/",
    "SOL": "https://solscan.io/tx/",
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


def get_channel_alert_keyboard(
    chain: str,
    tx_hash: str,
    from_addr: str,
    bot_username: str = "",
) -> InlineKeyboardMarkup:
    """URL deep-link buttons for public channel broadcasts.

    Never use callback_data on public channel messages: anyone can click them and
    callback payloads are not private. Each button opens a t.me deep link that
    re-enters the bot via /start with a routed payload (deepdive_/ask_/track_).
    """
    bot = (bot_username or Settings().BOT_USERNAME).strip().lstrip("@")
    code = _chain_code(chain)
    deepdive_url = f"https://t.me/{bot}?start=deepdive_{code}_{tx_hash}"
    ask_url = f"https://t.me/{bot}?start=ask_{code}_{tx_hash}"
    track_url = f"https://t.me/{bot}?start=track_{code}_{from_addr}"
    explorer_url = f"{_EXPLORER_BASE.get(code, _EXPLORER_BASE['ETH'])}{tx_hash}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✨ Deep Dive with AI", url=deepdive_url),
                InlineKeyboardButton(text="💬 Ask AI About Tx", url=ask_url),
            ],
            [
                InlineKeyboardButton(text="🕵️ Track This Entity", url=track_url),
                InlineKeyboardButton(text="🔍 View on Explorer", url=explorer_url),
            ],
        ]
    )

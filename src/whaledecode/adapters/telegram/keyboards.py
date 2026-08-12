from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_keyboard(tx_hash: str, bot_username: str = "") -> InlineKeyboardMarkup:
    bot = bot_username.strip().lstrip("@") or "whaledecodebot"
    deep_link = f"https://t.me/{bot}?start=analyze_{tx_hash}" if tx_hash else f"https://t.me/{bot}"
    explorer = f"https://etherscan.io/tx/{tx_hash}" if tx_hash else "https://etherscan.io"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Deep Dive with AI", url=deep_link)],
        [InlineKeyboardButton(text="⚲ View on Explorer", url=explorer)],
    ])

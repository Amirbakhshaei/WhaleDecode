from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_keyboard(tx_hash: str) -> InlineKeyboardMarkup:
    deep_link = f"https://t.me/whaledecodebot?start={tx_hash}" if tx_hash else "https://t.me/whaledecodebot"
    explorer = f"https://etherscan.io/tx/{tx_hash}" if tx_hash else "https://etherscan.io"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Deep Dive with AI", url=deep_link)],
        [InlineKeyboardButton(text="⚲ View on Explorer", url=explorer)],
    ])

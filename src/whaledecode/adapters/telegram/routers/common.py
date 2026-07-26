from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

common_router = Router(name="common")


@common_router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🐋 *WhaleDecode*\n\n"
        "I monitor smart-money wallets and alert you to interesting on-chain activity.\n\n"
        "Commands:\n"
        "`/wallets` — browse curated wallets\n"
        "`/track <id>` — track a wallet\n"
        "`/untrack <id>` — stop tracking\n"
        "`/chat <question>` — ask the AI agent\n"
        "`/alerts` — view your alerts\n"
        "`/help` — this message"
    )


@common_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await cmd_start(message)

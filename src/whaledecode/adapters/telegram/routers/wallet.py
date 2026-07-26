from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

wallet_router = Router(name="wallet")


@wallet_router.message(Command("wallets"))
async def cmd_wallets(message: Message) -> None:
    await message.answer("Curated wallets — coming soon. Use the Gradio UI or wait for Phase 6 completion.")


@wallet_router.message(Command("track"))
async def cmd_track(message: Message) -> None:
    await message.answer("Tracking not yet implemented. Use the Gradio UI.")


@wallet_router.message(Command("untrack"))
async def cmd_untrack(message: Message) -> None:
    await message.answer("Untracking not yet implemented. Use the Gradio UI.")

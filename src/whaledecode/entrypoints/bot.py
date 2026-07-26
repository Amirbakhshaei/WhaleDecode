import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from whaledecode.adapters.telegram.middleware import ThrottlingMiddleware
from whaledecode.adapters.telegram.routers import (
    admin_router,
    chat_router,
    common_router,
    wallet_router,
)
from whaledecode.config.settings import Settings


async def run_bot(settings: Settings) -> None:
    log = structlog.get_logger()

    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )
    dp = Dispatcher()
    dp.include_routers(common_router, wallet_router, chat_router, admin_router)
    dp.message.middleware(ThrottlingMiddleware())

    @dp.startup()
    async def on_startup():
        log.info("bot_started", bot_name=await bot.get_my_name())

    @dp.shutdown()
    async def on_shutdown():
        log.info("bot_stopped")

    log.info("bot_polling_start")
    await dp.start_polling(bot)

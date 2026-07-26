import structlog

from whaledecode.config.settings import Settings


async def run_bot(settings: Settings) -> None:
    log = structlog.get_logger()

    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )
    dp = Dispatcher()

    @dp.startup()
    async def on_startup():
        log.info("bot_started", bot_name=await bot.get_my_name())

    @dp.shutdown()
    async def on_shutdown():
        log.info("bot_stopped")

    log.info("bot_polling_start")
    await dp.start_polling(bot)

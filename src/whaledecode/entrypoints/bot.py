import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.telegram.dispatcher import TelegramAlertDispatcher
from whaledecode.adapters.telegram.middleware import ThrottlingMiddleware
from whaledecode.adapters.telegram.routers import (
    admin_router,
    callback_router,
    chat_router,
    common_router,
    payments_router,
    wallet_router,
)
from whaledecode.application.services.investigation import build_investigation_service
from whaledecode.application.services.wallet import WalletService
from whaledecode.config.settings import Settings
from whaledecode.entrypoints.seed import ensure_curated_wallets_seeded


def build_telegram_app(settings: Settings) -> tuple[Bot, Dispatcher]:
    """Build and configure the Telegram bot and dispatcher. Does NOT start polling."""
    log = structlog.get_logger()

    session_factory, investigation_service, reasoner = build_investigation_service(settings)

    alert_dispatcher = TelegramAlertDispatcher()

    def _uow() -> UnitOfWork:
        return UnitOfWork(session_factory)

    wallet_service = WalletService(_uow)

    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp["uow_factory"] = _uow
    dp["wallet_service"] = wallet_service
    dp["investigation_service"] = investigation_service
    dp["alert_dispatcher"] = alert_dispatcher
    dp["bot"] = bot
    dp["settings"] = settings
    dp["reasoner"] = reasoner

    dp.include_routers(common_router, wallet_router, chat_router, admin_router, callback_router, payments_router)
    dp.message.middleware(ThrottlingMiddleware())

    @dp.startup()
    async def on_startup():
        alert_dispatcher.set_bot(bot)
        await ensure_curated_wallets_seeded(session_factory)
        log.info("bot_started", bot_name=await bot.get_my_name())

    @dp.shutdown()
    async def on_shutdown():
        await reasoner.close()
        log.info("bot_stopped")

    return bot, dp


async def start_bot(settings: Settings) -> None:
    """Legacy entrypoint for standalone polling mode (kept for compatibility)."""
    bot, dp = build_telegram_app(settings)
    log = structlog.get_logger()
    log.info("bot_polling_start")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

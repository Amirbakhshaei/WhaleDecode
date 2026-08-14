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

log = structlog.get_logger()


async def _on_error(update, exception: Exception | None = None, **kwargs) -> bool:
    """Global handler: surface failures instead of silently dropping updates.

    Without this, any exception inside a command handler is swallowed by the
    polling loop and the user gets no reply — the classic 'bot commands don't
    work' symptom. We log the traceback and send a safe user-facing message.

    aiogram delivers the error as an ``ErrorEvent``; the original ``Update`` is on
    ``update.update`` and the raised exception on ``update.exception``."""
    exc = exception or getattr(update, "exception", None)
    original = getattr(update, "update", update)
    message = getattr(original, "message", None)
    if message is None:
        callback = getattr(original, "callback_query", None)
        message = getattr(callback, "message", None)
    log.error("telegram_update_failed", exc_info=exc, update_id=getattr(original, "update_id", None))
    if message is not None:
        try:
            await message.answer("⚠️ Something went wrong processing that. The team has been notified.")
        except Exception:  # noqa: BLE001 - never let the error handler crash
            pass
    return True


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
    dp.errors.register(_on_error)

    @dp.startup()
    async def on_startup():
        alert_dispatcher.set_bot(bot)
        # Don't let a seed failure abort the whole bot; log and continue.
        try:
            await ensure_curated_wallets_seeded(session_factory)
        except Exception as e:  # noqa: BLE001
            log.error("curated_wallets_seed_failed", error=str(e), exc_info=True)
        try:
            bot_name = await bot.get_my_name()
        except Exception:  # noqa: BLE001 - don't let a Telegram API hiccup kill startup
            bot_name = "unknown"
        log.info("bot_started", bot_name=bot_name)

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

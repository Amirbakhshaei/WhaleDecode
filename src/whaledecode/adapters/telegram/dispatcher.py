import structlog
from aiogram import Bot

from whaledecode.domain.ports.alert_dispatcher import AlertDispatcherPort


class TelegramAlertDispatcher(AlertDispatcherPort):
    def __init__(self) -> None:
        self._log = structlog.get_logger()
        self._bot: Bot | None = None

    def set_bot(self, bot: Bot) -> None:
        self._bot = bot

    async def dispatch(self, user_id: int, message: str, buttons: list[list[dict]] | None = None) -> bool:
        bot = self._bot
        if bot is None:
            self._log.warning("dispatch_alert_no_bot", user_id=user_id)
            return False
        try:
            await bot.send_message(chat_id=user_id, text=message)
            self._log.info("dispatch_alert", user_id=user_id, preview=message[:50])
            return True
        except Exception as e:
            self._log.error("dispatch_alert_error", user_id=user_id, error=str(e))
            return False

    async def dispatch_briefing(self, user_id: int, message: str) -> bool:
        bot = self._bot
        if bot is None:
            self._log.warning("dispatch_briefing_no_bot", user_id=user_id)
            return False
        try:
            await bot.send_message(chat_id=user_id, text=message)
            self._log.info("dispatch_briefing", user_id=user_id, preview=message[:50])
            return True
        except Exception as e:
            self._log.error("dispatch_briefing_error", user_id=user_id, error=str(e))
            return False

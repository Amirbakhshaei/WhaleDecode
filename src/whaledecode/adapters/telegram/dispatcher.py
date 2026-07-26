import structlog

from whaledecode.domain.ports.alert_dispatcher import AlertDispatcherPort


class TelegramAlertDispatcher(AlertDispatcherPort):
    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def dispatch(self, user_id: int, message: str, buttons: list[list[dict]] | None = None) -> bool:
        self._log.info("dispatch_alert", user_id=user_id, preview=message[:50])
        return True

    async def dispatch_briefing(self, user_id: int, message: str) -> bool:
        self._log.info("dispatch_briefing", user_id=user_id, preview=message[:50])
        return True

from typing import Protocol


class AlertDispatcherPort(Protocol):
    async def dispatch(self, user_id: int, message: str, buttons: list[list[dict]] | None = None) -> bool: ...

    async def dispatch_briefing(self, user_id: int, message: str) -> bool: ...

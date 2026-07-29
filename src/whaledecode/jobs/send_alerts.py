import structlog
from aiogram import Bot

from whaledecode.adapters.db.session import async_sessionmaker
from whaledecode.adapters.telegram.formatters.relay import RelayFormatter
from whaledecode.config.settings import Settings

log = structlog.get_logger()


async def send_alerts(session_factory: async_sessionmaker, bot: Bot, settings: Settings) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork

    relay = RelayFormatter(settings)

    uow = UnitOfWork(session_factory)
    async with uow:
        pending = await uow.alerts.list_by_status("pending", limit=50)
        if not pending:
            return

        for alert in pending:
            user = await uow.users.get_by_id(alert.user_id)
            if user is None or not user.alerts_enabled:
                alert.status = "suppressed"
                await uow.alerts.update(alert)
                continue

            event = await uow.candidate_events.get(alert.event_id)
            if event is None:
                alert.status = "failed"
                await uow.alerts.update(alert)
                continue

            run = await uow.agent_runs.get_by_trigger("event", alert.event_id)
            report = run.output_json if run else {}

            msg = relay.format_alert(event.model_dump(), report)
            try:
                await bot.send_message(chat_id=user.tg_id, text=msg)
                alert.status = "sent"
                log.info("alert_sent", alert_id=alert.id, user_id=user.id)
            except Exception as e:
                log.error("alert_send_failed", alert_id=alert.id, error=str(e))
                alert.status = "failed"
            await uow.alerts.update(alert)
        await uow.commit()

import structlog
from aiogram import Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from whaledecode.adapters.telegram.user_access import get_or_create_user

log = structlog.get_logger()
callback_router = Router(name="callbacks")


def alert_keyboard(alert_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Explain more", callback_data=f"alert:{alert_id}:explain")],
        [
            InlineKeyboardButton(text="Risks", callback_data=f"alert:{alert_id}:risks"),
            InlineKeyboardButton(text="Related", callback_data=f"alert:{alert_id}:related"),
        ],
        [InlineKeyboardButton(text="Ask follow-up", callback_data=f"alert:{alert_id}:follow")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@callback_router.callback_query(lambda c: c.data and c.data.startswith("alert:"))
async def handle_alert_callback(callback: types.CallbackQuery, uow_factory, investigation_service, **kwargs) -> None:
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Invalid callback.")
        return

    alert_id = parts[1]
    action = parts[2]
    user_id = callback.from_user.id

    await callback.answer()

    async with uow_factory() as uow:
        user = await get_or_create_user(user_id, callback.from_user.username, uow)
        alerts = await uow.alerts.list_by_user(user.id, limit=1)
        if not alerts:
            await callback.message.answer("Alert not found.")
            return
        alert = alerts[0]
        event = await uow.candidate_events.get(alert.event_id)

    if action == "risks":
        if event:
            await callback.message.answer(
                f"⚠️ <b>Risk Analysis</b>\n\nEvent score: {event.score:.1f}\n\n"
                "Large value transfers carry market impact risk. "
                "Always DYOR before making decisions."
            )
        else:
            await callback.message.answer("Event details not available.")
    elif action == "explain":
        context = f"Explain more about alert {alert_id}"
        resp = await investigation_service.chat(context)
        await callback.message.answer(resp[:4000])
    elif action == "related":
        context = f"Find related transactions and activity for alert {alert_id}"
        resp = await investigation_service.chat(context)
        await callback.message.answer(resp[:4000])
    elif action == "follow":
        await callback.message.answer(
            "What would you like to know more about? Type your question below."
        )
    else:
        await callback.message.answer("Unknown action.")

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.application.services.user_service import upgrade_to_paid
from whaledecode.domain.entities.admin_audit_log import AdminAuditLog

log = structlog.get_logger()

payments_router = Router(name="payments")

PREMIUM_TITLE = "WhaleDecode Premium"
PREMIUM_DESCRIPTION = (
    "Unlock unlimited agent queries, real-time memory, and priority SMC alerting."
)
PREMIUM_PRICE_STARS = 500
PREMIUM_PRICE = LabeledPrice(label="Premium Tier", amount=PREMIUM_PRICE_STARS)
PAYLOAD_PREFIX = "upgrade_tier_"

UPGRADE_CONFIRMATION = (
    "💎 <b>WhaleDecode Premium activated!</b>\n\n"
    "Unlimited agent queries, real-time memory, and priority SMC alerting are now yours. "
    "Thanks for supporting WhaleDecode."
)


def subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Subscribe for 500 Stars",
                    callback_data="subscribe:premium",
                )
            ]
        ]
    )


@payments_router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, **kwargs) -> None:
    await message.answer_invoice(
        title=PREMIUM_TITLE,
        description=PREMIUM_DESCRIPTION,
        payload=f"{PAYLOAD_PREFIX}{message.from_user.id}",
        currency="XTR",
        provider_token="",
        prices=[PREMIUM_PRICE],
    )


@payments_router.callback_query(F.data == "subscribe:premium")
async def on_subscribe_callback(callback: CallbackQuery, **kwargs) -> None:
    await callback.answer()
    await callback.message.answer_invoice(
        title=PREMIUM_TITLE,
        description=PREMIUM_DESCRIPTION,
        payload=f"{PAYLOAD_PREFIX}{callback.from_user.id}",
        currency="XTR",
        provider_token="",
        prices=[PREMIUM_PRICE],
    )


@payments_router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, uow_factory, **kwargs) -> None:
    payload = query.invoice_payload or ""
    if not payload.startswith(PAYLOAD_PREFIX):
        await query.answer(ok=False, error_message="Invalid payment payload.")
        return
    try:
        tg_id = int(payload[len(PAYLOAD_PREFIX) :])
    except ValueError:
        await query.answer(ok=False, error_message="Invalid payment payload.")
        return
    async with uow_factory() as uow:
        user = await get_or_create_user(tg_id, query.from_user.username, uow)
    if user is None:
        await query.answer(ok=False, error_message="Account not found. Press /start to register.")
        return
    await query.answer(ok=True)


@payments_router.message(F.successful_payment)
async def on_successful_payment(message: Message, uow_factory, **kwargs) -> None:
    payment = message.successful_payment
    tg_id = message.from_user.id
    async with uow_factory() as uow:
        user, _ = await upgrade_to_paid(uow, tg_id)
        audit = AdminAuditLog(
            admin_id=tg_id,
            action="stars_payment",
            target_type="user",
            target_id=user.id,
            diff_json={
                "telegram_payment_charge_id": payment.telegram_payment_charge_id,
                "provider_payment_charge_id": payment.provider_payment_charge_id,
                "amount": payment.total_amount,
                "currency": payment.currency,
            },
        )
        await uow.admin_audit_logs.create(audit)
        await uow.commit()
    log.info(
        "stars_payment_success",
        tg_id=tg_id,
        charge_id=payment.telegram_payment_charge_id,
        amount=payment.total_amount,
    )
    await message.answer(UPGRADE_CONFIRMATION)

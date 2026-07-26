from dataclasses import dataclass
from enum import StrEnum


class PlanCode(StrEnum):
    FREE = "free"
    PAID = "paid"


class AlertTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    WHALE = "whale"


class UserTier(StrEnum):
    FREE = "free"
    PAID = "paid"


@dataclass
class PlanLimits:
    chat_daily: int
    max_wallets: int
    alert_batch_minutes: int
    alert_delay_seconds: int
    tracked_wallets: int | None = None  # None = unlimited


FREE_LIMITS = PlanLimits(
    chat_daily=5,
    max_wallets=3,
    alert_batch_minutes=60,
    alert_delay_seconds=3600,
)

PAID_LIMITS = PlanLimits(
    chat_daily=50,
    max_wallets=999,
    alert_batch_minutes=0,
    alert_delay_seconds=5,
)


def get_limits(plan: PlanCode) -> PlanLimits:
    return FREE_LIMITS if plan == PlanCode.FREE else PAID_LIMITS

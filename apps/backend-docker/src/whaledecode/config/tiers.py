from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlanTier(Enum):
    FREE = "free"
    PAID = "paid"

    @classmethod
    def from_str(cls, s: str) -> PlanTier:
        for member in cls:
            if member.value == s:
                return member
        return cls.FREE


@dataclass(frozen=True)
class PlanLimits:
    chat_per_day: int
    max_tracked_wallets: int
    alert_immediacy: str  # "instant" or "batch"
    briefing_on_demand: bool


PLAN_LIMITS: dict[PlanTier, PlanLimits] = {
    PlanTier.FREE: PlanLimits(
        chat_per_day=5,
        max_tracked_wallets=3,
        alert_immediacy="batch",
        briefing_on_demand=False,
    ),
    PlanTier.PAID: PlanLimits(
        chat_per_day=50,
        max_tracked_wallets=100,
        alert_immediacy="instant",
        briefing_on_demand=True,
    ),
}


def get_limits(plan: str) -> PlanLimits:
    tier = PlanTier.from_str(plan)
    return PLAN_LIMITS[tier]

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.config.tiers import PlanLimits, get_limits
from whaledecode.domain.entities.user import User
from whaledecode.domain.exceptions import QuotaExceededError

UPGRADE_CTA_MESSAGE = (
    "You've exhausted your free daily intelligence budget. "
    "Upgrade to WhaleDecode PRO for unlimited investigations."
)


async def get_user_with_limits(uow: UnitOfWork, user_id: int) -> tuple[User, PlanLimits]:
    user = await uow.users.get_by_id(user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    limits = get_limits(user.plan)
    return user, limits


async def check_and_decrement_quota(
    uow: UnitOfWork, tg_id: int, user: User | None = None
) -> User:
    """Spend one free-tier intelligence query, if allowed.

    Free tier spends from ``queries_remaining``; paid tiers are unlimited.
    Caller is responsible for ``uow.commit()``. Raises ``QuotaExceededError``
    when a free user has no budget left.
    """
    account = user or await uow.users.get_by_tg_id(tg_id)
    if account is None:
        raise QuotaExceededError("Account not found. Press /start to register.")
    if account.tier == "free":
        if account.queries_remaining <= 0:
            raise QuotaExceededError(UPGRADE_CTA_MESSAGE)
        account.queries_remaining -= 1
        await uow.users.update(account)
    return account


async def upgrade_to_paid(uow: UnitOfWork, tg_id: int) -> tuple[User, bool]:
    """Promote a user to the PAID tier. Returns ``(user, was_upgrade)``.

    Caller is responsible for ``uow.commit()``.
    """
    account = await uow.users.get_by_tg_id(tg_id)
    if account is None:
        raise ValueError(f"User {tg_id} not found")
    if account.tier == "paid":
        return account, False
    account.plan = "paid"
    account.tier = "paid"
    await uow.users.update(account)
    return account, True

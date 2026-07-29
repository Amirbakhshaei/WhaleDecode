from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.config.tiers import PlanLimits, get_limits
from whaledecode.domain.entities.user import User


async def get_user_with_limits(uow: UnitOfWork, user_id: int) -> tuple[User, PlanLimits]:
    user = await uow.users.get_by_id(user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    limits = get_limits(user.plan)
    return user, limits

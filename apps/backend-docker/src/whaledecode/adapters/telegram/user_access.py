from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.domain.entities.user import User


async def get_or_create_user(tg_id: int, username: str | None, uow: UnitOfWork) -> User:
    existing = await uow.users.get_by_tg_id(tg_id)
    if existing:
        return existing
    user = User(tg_id=tg_id, username=username, plan="free")
    created = await uow.users.create(user)
    await uow.commit()
    return created

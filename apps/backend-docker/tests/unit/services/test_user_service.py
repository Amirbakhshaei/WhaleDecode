import pytest
from whaledecode.application.services.user_service import (
    check_and_decrement_quota,
    upgrade_to_paid,
)
from whaledecode.domain.entities.user import User
from whaledecode.domain.exceptions import QuotaExceededError


class FakeUsersRepo:
    def __init__(self, account: User | None = None):
        self._account = account
        self.updates: list[User] = []

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        return self._account

    async def get_by_id(self, user_id: int) -> User | None:
        return self._account

    async def update(self, user: User) -> None:
        self.updates.append(user.model_copy(deep=True))


class FakeUow:
    def __init__(self, repo: FakeUsersRepo):
        self.users = repo


@pytest.mark.asyncio
async def test_free_user_decrements_quota() -> None:
    repo = FakeUsersRepo(User(tg_id=1, tier="free", queries_remaining=5))
    result = await check_and_decrement_quota(FakeUow(repo), 1)
    assert result.queries_remaining == 4
    assert repo.updates[0].queries_remaining == 4


@pytest.mark.asyncio
async def test_free_user_at_zero_raises() -> None:
    repo = FakeUsersRepo(User(tg_id=1, tier="free", queries_remaining=0))
    with pytest.raises(QuotaExceededError):
        await check_and_decrement_quota(FakeUow(repo), 1)
    assert repo.updates == []


@pytest.mark.asyncio
async def test_paid_user_is_unlimited() -> None:
    repo = FakeUsersRepo(User(tg_id=1, tier="paid", queries_remaining=0))
    result = await check_and_decrement_quota(FakeUow(repo), 1)
    assert result.queries_remaining == 0
    assert repo.updates == []


@pytest.mark.asyncio
async def test_admin_id_exempt_from_quota() -> None:
    # Admin Telegram IDs must bypass the free-tier quota even at zero remaining.
    repo = FakeUsersRepo(User(tg_id=1, tier="free", queries_remaining=0))
    result = await check_and_decrement_quota(FakeUow(repo), 1, admin_ids=[1, 2])
    assert result.queries_remaining == 0
    assert repo.updates == []


@pytest.mark.asyncio
async def test_non_admin_not_exempt_when_admin_ids_given() -> None:
    repo = FakeUsersRepo(User(tg_id=3, tier="free", queries_remaining=0))
    with pytest.raises(QuotaExceededError):
        await check_and_decrement_quota(FakeUow(repo), 3, admin_ids=[1, 2])
    assert repo.updates == []


@pytest.mark.asyncio
async def test_missing_account_raises() -> None:
    with pytest.raises(QuotaExceededError):
        await check_and_decrement_quota(FakeUow(FakeUsersRepo(None)), 99)


@pytest.mark.asyncio
async def test_upgrade_to_paid_promotes_free_user() -> None:
    repo = FakeUsersRepo(User(tg_id=1, tier="free", plan="free"))
    user, was_upgrade = await upgrade_to_paid(FakeUow(repo), 1)
    assert was_upgrade is True
    assert user.tier == "paid"
    assert user.plan == "paid"
    assert repo.updates[0].tier == "paid"


@pytest.mark.asyncio
async def test_upgrade_to_paid_is_idempotent() -> None:
    repo = FakeUsersRepo(User(tg_id=1, tier="paid", plan="paid"))
    user, was_upgrade = await upgrade_to_paid(FakeUow(repo), 1)
    assert was_upgrade is False
    assert user.tier == "paid"
    assert repo.updates == []


@pytest.mark.asyncio
async def test_upgrade_to_paid_missing_account_raises() -> None:
    with pytest.raises(ValueError):
        await upgrade_to_paid(FakeUow(FakeUsersRepo(None)), 99)

import pytest
from whaledecode.application.services.user_service import check_and_decrement_quota
from whaledecode.domain.entities.user import User
from whaledecode.domain.exceptions import QuotaExceededError


class FakeUsersRepo:
    def __init__(self, account: User | None = None):
        self._account = account
        self.updates: list[User] = []

    async def get_by_tg_id(self, tg_id: int) -> User | None:
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
async def test_missing_account_raises() -> None:
    with pytest.raises(QuotaExceededError):
        await check_and_decrement_quota(FakeUow(FakeUsersRepo(None)), 99)

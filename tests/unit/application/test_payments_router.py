from dataclasses import dataclass, field
from typing import Any

import pytest
from whaledecode.adapters.telegram.routers.payments import (
    PAYLOAD_PREFIX,
    PREMIUM_DESCRIPTION,
    PREMIUM_TITLE,
    on_pre_checkout,
    on_successful_payment,
)
from whaledecode.domain.entities.admin_audit_log import AdminAuditLog
from whaledecode.domain.entities.user import User


class FakeUsersRepo:
    def __init__(self, account: User | None = None):
        self._account = account
        self.updates: list[User] = []

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        return self._account

    async def update(self, user: User) -> None:
        self.updates.append(user.model_copy(deep=True))


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[AdminAuditLog] = []

    async def create(self, entry: AdminAuditLog) -> AdminAuditLog:
        self.entries.append(entry)
        return entry


class FakeUow:
    def __init__(self, account: User | None = None):
        self.users = FakeUsersRepo(account)
        self.admin_audit_logs = FakeAuditRepo()
        self.committed = 0

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1


class FakeFrom:
    def __init__(self, tg_id: int, username: str | None = None) -> None:
        self.id = tg_id
        self.username = username


@dataclass
class FakeQuery:
    payload: str
    username: str | None = None
    from_user: FakeFrom | None = None
    answer_calls: list[dict[str, bool | str | None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.from_user = FakeFrom(42, self.username)

    @property
    def invoice_payload(self) -> str:
        return self.payload

    async def answer(self, ok: bool, error_message: str | None = None, **kwargs: Any) -> None:
        self.answer_calls.append({"ok": ok, "error_message": error_message})


@dataclass
class FakePayment:
    telegram_payment_charge_id: str = "charge_123"
    provider_payment_charge_id: str = "provider_456"
    total_amount: int = 500
    currency: str = "XTR"
    invoice_payload: str = ""


@dataclass
class FakeMessage:
    from_user: FakeFrom
    successful_payment: FakePayment
    answers: list[str] = field(default_factory=list)
    reply_answers: list[str] = field(default_factory=list)

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


@pytest.mark.asyncio
async def test_pre_checkout_valid_payload_answers_ok() -> None:
    query = FakeQuery(payload=f"{PAYLOAD_PREFIX}42")
    await on_pre_checkout(query, uow_factory=lambda: FakeUow(User(tg_id=42)))
    assert query.answer_calls == [{"ok": True, "error_message": None}]


@pytest.mark.asyncio
async def test_pre_checkout_bad_payload_answers_fail() -> None:
    query = FakeQuery(payload="garbage")
    await on_pre_checkout(query, uow_factory=lambda: FakeUow(User(tg_id=42)))
    assert query.answer_calls[0]["ok"] is False


@pytest.mark.asyncio
async def test_successful_payment_upgrades_and_audits() -> None:
    message = FakeMessage(from_user=FakeFrom(42), successful_payment=FakePayment())
    uow = FakeUow(User(id=7, tg_id=42, tier="free"))
    await on_successful_payment(message, uow_factory=lambda: uow)

    assert uow.users.updates[0].tier == "paid"
    assert uow.committed == 1
    assert len(uow.admin_audit_logs.entries) == 1
    entry = uow.admin_audit_logs.entries[0]
    assert entry.action == "stars_payment"
    assert entry.target_id == 7
    assert entry.diff_json["telegram_payment_charge_id"] == "charge_123"
    assert len(message.answers) == 1
    assert "Premium activated" in message.answers[0]


def test_router_exports_expected_constants() -> None:
    assert PREMIUM_TITLE == "WhaleDecode Premium"
    assert "unlimited agent queries" in PREMIUM_DESCRIPTION

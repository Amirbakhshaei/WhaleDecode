"""Integration smoke tests for the Telegram command layer.

The command handlers had zero coverage, and a missing global error handler meant
any runtime failure was swallowed silently (the "bot commands don't work, no reply
at all" symptom). These tests build a real Dispatcher with the production routers,
inject fakes via workflow_data, and assert every command produces a reply. The
routers are module-level singletons, so we build one dispatcher and exercise all
commands through it (re-attaching the same routers to a second dispatcher raises).
"""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, Update
from whaledecode.adapters.telegram.routers import (
    admin_router,
    callback_router,
    chat_router,
    common_router,
    payments_router,
    wallet_router,
)
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.entities.user import User
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.entrypoints.bot import _on_error


class _RecordingSession(BaseSession):
    """Capture outgoing messages without hitting the Telegram API."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    async def make_request(self, bot, method, timeout=None):
        data = method.model_dump() if hasattr(method, "model_dump") else {}
        if isinstance(data, dict) and data.get("text") is not None:
            self.sent.append(data["text"])
        return {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 999, "is_bot": True, "first_name": "WhaleDecode"},
            "text": data.get("text") if isinstance(data, dict) else "",
        }

    async def close(self):
        pass

    async def stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


class _FakeUsers:
    def __init__(self) -> None:
        self._user = User(id=1, tg_id=42, username="tester")

    async def get_by_tg_id(self, tg_id):
        return self._user

    async def get_by_id(self, uid):
        return self._user

    async def create(self, u):
        return u

    async def update(self, u):
        return None

    async def list_by_plan(self, plan):
        return []


class _FakeWallets:
    async def list_active(self, chain=None):
        return []

    async def get(self, wid):
        return None

    async def search_by_label_or_category(self, query, limit=5):
        return []


class _FakeTracked:
    async def count_active_by_user(self, uid):
        return 0

    async def list_by_user(self, uid):
        return []


class _FakeAlerts:
    async def list_by_user(self, uid, limit=50):
        return []


class _FakeUow:
    def __init__(self) -> None:
        self.users = _FakeUsers()
        self.curated_wallets = _FakeWallets()
        self.tracked_wallets = _FakeTracked()
        self.alerts = _FakeAlerts()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeInvestigation:
    async def chat(self, msg, context=None, thread_id=None, model=None):
        return "Investigation result text."

    async def generate_briefing(self, user_id):
        return "Briefing text."


class _FakeWalletService:
    async def track(self, *a, **k):
        pass

    async def untrack(self, *a, **k):
        pass


class _FakeSettings:
    ADMIN_USER_IDS: list[int] = []
    CHANNEL_PUBLISH_ENABLED = False
    CHANNEL_CHAT_ID = None
    CHANNEL_MAX_DAILY = 10
    BOT_USERNAME = "whaledecodebot"
    DISCLAIMER_TEXT = "Not financial advice."


class _BoomUow(_FakeUow):
    async def __aenter__(self):
        raise RuntimeError("db down")


class _MatchingWallets(_FakeWallets):
    async def search_by_label_or_category(self, query, limit=5):
        return [
            CuratedWallet(
                address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
                chain=Chain.ETH,
                label="Binance",
                quality_score=90,
            )
        ]


class _MatchUow(_FakeUow):
    def __init__(self) -> None:
        super().__init__()
        self.curated_wallets = _MatchingWallets()


# Routers are module-level singletons and may only attach to ONE Dispatcher.
# Build a single shared dispatcher once and reuse it across every test in this
# module (re-attaching to a second Dispatcher raises).
_SHARED_DP: Dispatcher | None = None
_SHARED_BOT: Bot | None = None
_SHARED_SESSION: _RecordingSession | None = None


def _get_shared_dp() -> tuple[Bot, Dispatcher, _RecordingSession]:
    global _SHARED_DP, _SHARED_BOT, _SHARED_SESSION
    if _SHARED_DP is None:
        _SHARED_SESSION = _RecordingSession()
        _SHARED_BOT = Bot(token="123456:FAKE", session=_SHARED_SESSION)
        _SHARED_DP = Dispatcher()
        _SHARED_DP["uow_factory"] = _FakeUow
        _SHARED_DP["investigation_service"] = _FakeInvestigation()
        _SHARED_DP["wallet_service"] = _FakeWalletService()
        _SHARED_DP["settings"] = _FakeSettings()
        _SHARED_DP.errors.register(_on_error)
        _SHARED_DP.include_routers(
            common_router, wallet_router, chat_router, admin_router, callback_router, payments_router
        )
    return _SHARED_BOT, _SHARED_DP, _SHARED_SESSION


def _build_dp() -> tuple[Bot, Dispatcher, _RecordingSession]:
    bot, dp, session = _get_shared_dp()
    dp["uow_factory"] = _FakeUow
    dp["investigation_service"] = _FakeInvestigation()
    dp["wallet_service"] = _FakeWalletService()
    dp["settings"] = _FakeSettings()
    return bot, dp, session


async def _send(bot, dp, text: str) -> None:
    from_user = {"id": 42, "is_bot": False, "first_name": "tester"}
    msg = Message(
        message_id=1, date=0, chat={"id": 1, "type": "private"}, from_user=from_user, text=text
    )
    await dp.feed_update(bot, Update(update_id=1, message=msg))


async def test_all_commands_produce_replies_and_errors_surface():
    """Every command must yield a reply, and a crashing handler must surface one.

    The routers are module-level singletons that attach to a single dispatcher, so
    we build one dispatcher and exercise all commands through it."""
    bot, dp, session = _build_dp()

    await _send(bot, dp, "/start")
    assert any("WhaleDecode" in s for s in session.sent), session.sent

    session.sent.clear()
    await _send(bot, dp, "/help")
    assert any("WhaleDecode" in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/status")
    assert any("Your Status" in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/wallets")
    assert session.sent

    session.sent.clear()
    await _send(bot, dp, "/ask what did 0x742d... do recently?")
    assert any("Investigation result text." in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/decode 0x1234abcd")
    assert any("Investigation result text." in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/briefing")
    assert any("Briefing text." in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/track 5")
    assert any("not found" in s.lower() for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/alerts")
    assert any("Alerts" in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/start track_0xabcd1234abcd1234abcd1234abcd1234abcd1234")
    assert any("Investigation result text." in s for s in session.sent)

    session.sent.clear()
    await _send(bot, dp, "/start some_unknown_payload")
    assert session.sent, "unknown deep-link payload must still reply, not silently drop"

    # Now verify a crashing handler surfaces the error-handler reply instead of silence.
    session.sent.clear()
    dp["uow_factory"] = _BoomUow
    await _send(bot, dp, "/status")
    assert any("went wrong" in s for s in session.sent), session.sent

    # /ask triage: entity name → curated-wallet hits (DB search, no LLM); address/hash → investigation.
    session.sent.clear()
    dp["uow_factory"] = _MatchUow
    await _send(bot, dp, "/ask binance")
    assert any("Found 1 entities" in s for s in session.sent), session.sent
    assert any("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18" in s for s in session.sent), session.sent

    session.sent.clear()
    dp["uow_factory"] = _FakeUow
    await _send(bot, dp, "/ask 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18")
    assert any("Investigation result text." in s for s in session.sent), session.sent

    session.sent.clear()
    tx = "0x" + "a" * 64
    await _send(bot, dp, f"/ask {tx}")
    assert any("Investigation result text." in s for s in session.sent), session.sent


class _HubCuratedWallets(_FakeWallets):
    async def get_by_address_and_chain(self, address, chain):
        return CuratedWallet(id=1, address=address, chain=Chain.ETH, label="Test Whale")


class _HubUow(_FakeUow):
    def __init__(self) -> None:
        super().__init__()
        self.curated_wallets = _HubCuratedWallets()


class _RecordingWalletService:
    def __init__(self) -> None:
        self.tracked: list = []
        self.untracked: list = []

    async def track(self, uid, wid, chain):
        self.tracked.append((uid, wid, str(chain)))

    async def untrack(self, uid, wid):
        self.untracked.append((uid, wid))


async def _send_callback(bot, dp, data: str) -> None:
    from aiogram.types import CallbackQuery

    msg = Message(
        message_id=1, date=0, chat={"id": 1, "type": "private"},
        from_user={"id": 42, "is_bot": False, "first_name": "tester"}, text="hub",
    )
    cb = CallbackQuery(
        id="1", from_user={"id": 42, "is_bot": False, "first_name": "tester"},
        chat_instance="x", message=msg, data=data,
    )
    await dp.feed_update(bot, Update(update_id=1, callback_query=cb))


def _hub_dp(wallet_service) -> tuple[Bot, Dispatcher, _RecordingSession]:
    bot, dp, session = _get_shared_dp()
    dp["uow_factory"] = _HubUow
    dp["investigation_service"] = _FakeInvestigation()
    dp["wallet_service"] = wallet_service
    dp["settings"] = _FakeSettings()
    return bot, dp, session


async def test_tx_deep_link_shows_intelligence_hub():
    bot, dp, session = _hub_dp(_FakeWalletService())
    session.sent.clear()
    await _send(bot, dp, "/start tx_ETH_0x" + "a" * 62)
    assert any("Intelligence Hub" in s for s in session.sent), session.sent
    assert any("Choose an investigation action" in s for s in session.sent), session.sent


async def test_wallet_deep_link_shows_dossier_hub():
    bot, dp, session = _hub_dp(_FakeWalletService())
    session.sent.clear()
    await _send(bot, dp, "/start wallet_ETH_0x" + "a" * 40)
    assert any("Wallet Dossier Hub" in s for s in session.sent), session.sent
    assert any("Select an action" in s for s in session.sent), session.sent


async def test_hub_track_callback_toggles_subscription():
    wsvc = _RecordingWalletService()
    bot, dp, session = _hub_dp(wsvc)
    session.sent.clear()
    await _send_callback(bot, dp, "act:track:ETH:0x" + "a" * 40)
    assert wsvc.tracked, session.sent
    assert wsvc.tracked[0][0] == 1  # fake user.id
    assert wsvc.tracked[0][1] == 1  # curated wallet id

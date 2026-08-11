"""FastAPI app with Telegram bot lifespan + Alchemy webhook endpoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.normalizer import _classify_event, parse_token_amount
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.services.investigation import (
    build_investigation_service,
)
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.policies.sentinel import SentinelEngine
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.domain.value_objects.hash import Hash
from whaledecode.entrypoints.bot import build_telegram_app
from whaledecode.entrypoints.worker import launch_supervisor_tasks

logger = logging.getLogger(__name__)

_NETWORK_TO_CHAIN: dict[str, Chain] = {
    "ETH_MAINNET": Chain.ETH,
    "BASE_MAINNET": Chain.BASE,
    "ARB_MAINNET": Chain.ARB,
}

_sentinel = SentinelEngine()


def verify_alchemy_signature(body: bytes, signature: str | None, keys: list[str]) -> bool:
    """Hex HMAC-SHA256 of the raw request body signed with any of the webhook signing keys."""
    if not signature or not keys:
        return False
    import hashlib
    import hmac
    for k in keys:
        digest = hmac.new(k.encode(), body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest.encode(), signature.encode()):
            return True
    return False


def _hex_int(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16)
        except ValueError:
            return default
    return default


def _coerce_numeric(value: Any, default: float = 0.0) -> float:
    """Coerce a webhook ``value`` to float; hex strings → default.

    Alchemy sends token-transfer ``value`` as a hex string of *raw* token units,
    not a USD figure — treating it as USD would inflate a 6-decimal token by
    10^12. Only real numerics are accepted; hex/unknown → ``default`` (the
    deterministic gate re-prices true USD downstream from ``token_amount``).
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("0x"):
            return default
        try:
            return float(stripped)
        except ValueError:
            return default
    return default


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start bot polling + consumer supervisor on startup, stop on shutdown."""
    settings = app.state.settings
    logger.info("Starting Telegram Bot in the background...")
    bot, dp = build_telegram_app(settings)
    await dp.emit_startup()
    await bot.delete_webhook(drop_pending_updates=True)
    app.state.bot = bot
    app.state.dp = dp
    app.state.polling_task = dp.start_polling(bot)
    logger.info("Bot polling started")

    # Start consumer supervisor (BackgroundAIWorker + alert loop + cron jobs)
    stop_event = asyncio.Event()
    app.state.stop_event = stop_event
    app.state.supervisor_tasks = launch_supervisor_tasks(
        app.state.session_factory,
        app.state.investigation_service,
        settings,
        bot,
        stop_event,
    )
    logger.info("Consumer supervisor started")

    yield

    logger.info("Shutting down Telegram Bot and consumer supervisor...")
    stop_event.set()
    app.state.polling_task.cancel()
    for task in app.state.supervisor_tasks:
        task.cancel()
    try:
        await app.state.polling_task
    except asyncio.CancelledError:
        pass
    await asyncio.gather(*app.state.supervisor_tasks, return_exceptions=True)
    await dp.emit_shutdown()
    await bot.session.close()


# Initialize settings and deps once at module load
settings = Settings()
session_factory, investigation_service, _ = build_investigation_service(settings)

app = FastAPI(lifespan=lifespan)
app.state.settings = settings
app.state.session_factory = session_factory
app.state.investigation_service = investigation_service


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "WhaleDecode Webhook Receiver"}


@app.post("/webhook/alchemy")
async def alchemy_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_alchemy_signature: str = Header(None),
):
    raw_body = await request.body()
    if not verify_alchemy_signature(raw_body, x_alchemy_signature, settings.webhook_signing_keys):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    background_tasks.add_task(
        _process_webhook_payload,
        payload,
        settings,
        session_factory,
    )
    return {"status": "accepted"}


async def _process_webhook_payload(
    payload: dict[str, Any],
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Process webhook payload in background - only ingest and persist as pending."""
    if payload.get("type") != "ADDRESS_ACTIVITY":
        return
    event = payload.get("event") or {}
    chain = _NETWORK_TO_CHAIN.get(event.get("network"))
    if chain is None:
        logger.warning("webhook_unknown_network", extra={"network": event.get("network")})
        return

    # Early rejection: drop zero-value native transfers and empty contract calls
    # before any DB session or candidate_event insert — this is the write-
    # amplification guard that keeps dust/approve/zero-call spam off the queue.
    raw_activities = event.get("activity") or []
    activities = [a for a in raw_activities if a.get("hash") and not _is_ignorable_activity(a)]
    if len(activities) != len(raw_activities):
        logger.info("webhook_dropped_ignorable", extra={"dropped": len(raw_activities) - len(activities)})

    # Chain floor gate: drop sub-floor USD noise in memory before any DB session.
    floored = [a for a in activities if not _below_chain_floor(a, chain)]
    if len(floored) != len(activities):
        logger.info(
            "webhook_dropped_below_floor",
            extra={"dropped": len(activities) - len(floored), "chain": chain.name},
        )
    activities = floored
    if not activities:
        return

    async with UnitOfWork(session_factory) as uow:
        wallets = await uow.curated_wallets.list_active(chain=chain.name)
    wallet_map = {w.address.lower(): w for w in wallets if w.id is not None}

    for activity in activities:
        wallet = None
        for side in ("fromAddress", "toAddress"):
            addr = activity.get(side)
            if addr and addr.lower() in wallet_map:
                wallet = wallet_map[addr.lower()]
                break
        if wallet is None:
            continue

        # Build candidate data and insert directly as pending
        candidate_data = _build_candidate_data(activity, chain, wallet)
        async with UnitOfWork(session_factory) as uow:
            await uow.candidate_events.create_pending(candidate_data)
            await uow.commit()
        logger.info("webhook_candidate_pending", extra={"dedupe_key": candidate_data["dedupe_key"]})


def _below_chain_floor(activity: dict[str, Any], chain: Chain) -> bool:
    """True if the activity's *known* USD value is under the chain's noise floor.

    Hex/absent values (coerced to 0.0 by ``_coerce_numeric``) carry no USD figure
    and are re-priced downstream by the event gate, so they are never gated here.
    """
    from whaledecode.config.chain_rules import CHAIN_RULES

    rule = CHAIN_RULES.get(chain.name)
    floor = rule.min_usd_threshold if rule else 50_000.0
    value_usd = _coerce_numeric(activity.get("value"))
    return value_usd > 0.0 and value_usd < floor


def _is_ignorable_activity(activity: dict[str, Any]) -> bool:
    """Discard zero-value native transfers and empty contract calls.

    A native (``category == "external"``) transfer whose raw value is 0 is a
    smart-contract interaction / approve / zero-value call — not a transfer
    worth persisting. Token (erc20/721/1155) activities are never gated here;
    their value is priced downstream via contract decimals.
    """
    if activity.get("category") != "external":
        return False
    raw_value = (activity.get("rawContract") or {}).get("rawValue", "0x0")
    if raw_value not in ("0x0", "0x", None):
        return False
    try:
        value_float = float(activity.get("value") or 0.0)
    except (TypeError, ValueError):
        value_float = 0.0
    return value_float == 0.0


def _token_decimals(activity: dict[str, Any]) -> int:
    """Resolve the token's decimal places from the activity, defaulting to 18.

    Alchemy includes the hint as ``rawContract.decimal``/``rawContract.decimals``
    on some payloads; when absent, 18 is the ERC-20 default (deterministic, and
    never an inflation of a 6-decimal token when the hint *is* present).
    """
    raw_contract = activity.get("rawContract") or {}
    for key in ("decimal", "decimals"):
        value = raw_contract.get(key)
        if value is not None and value != "":
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return 18


def _build_candidate_data(
    activity: dict[str, Any],
    chain: Chain,
    wallet: CuratedWallet,
) -> dict[str, Any]:
    """Build candidate event data dict for repository insertion."""
    raw_value = (activity.get("rawContract") or {}).get("rawValue")
    decimals = _token_decimals(activity)
    token_amount = (
        parse_token_amount(str(raw_value), decimals)
        if raw_value and isinstance(raw_value, str)
        else _coerce_numeric(activity.get("value"))
    )
    value_usd = _coerce_numeric(activity.get("value"))
    log_obj = activity.get("log") or {}
    topics = log_obj.get("topics") or []
    event_type = _classify_event(topics, log_obj.get("address", "")) if topics else "TRANSFER"
    log_index = _hex_int(log_obj.get("logIndex"))
    chain_label = chain.label()

    raw_json = dict(activity)
    raw_json["value_usd"] = value_usd
    raw_json["token_amount"] = token_amount
    raw_json["decimals"] = decimals
    tx_hash = Hash(activity["hash"])

    return {
        "wallet_id": wallet.id,
        "chain": chain_label,
        "tx_hash": str(tx_hash),
        "log_index": log_index,
        "block_number": _hex_int(activity.get("blockNum")),
        "event_type": event_type,
        "raw_json": raw_json,
        "score": _score_activity(event_type, value_usd, wallet.id, str(tx_hash)),
        "dedupe_key": f"{wallet.id}:{activity['hash']}:{log_index}",
    }


def _activity_candidate(
    activity: dict[str, Any],
    chain: Chain,
    wallet: CuratedWallet,
) -> CandidateEvent:
    """Shape one Alchemy Address Activity into our internal candidate event (legacy for tests)."""
    data = _build_candidate_data(activity, chain, wallet)
    return CandidateEvent(**data)


def _score_activity(event_type: str, value_usd: float, wallet_id: int, tx_hash: str) -> float:
    """Deterministic SENTINEL score for one curated-wallet activity."""
    return _sentinel.score(
        {
            "event_type": event_type,
            "value_usd": value_usd,
            "wallet_id": wallet_id,
            "tx_hash": tx_hash,
        },
        curated_wallet_ids={wallet_id},
    )


def _score_candidate(candidate: CandidateEvent) -> float:
    return _score_activity(
        candidate.event_type,
        candidate.raw_json.get("value_usd", 0.0),
        candidate.wallet_id,
        str(candidate.tx_hash),
    )

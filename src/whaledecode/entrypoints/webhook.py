"""FastAPI app with Telegram bot lifespan + Alchemy webhook endpoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.normalizer import _classify_event
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

    async with UnitOfWork(session_factory) as uow:
        wallets = await uow.curated_wallets.list_active(chain=chain.name)
    wallet_map = {w.address.lower(): w for w in wallets if w.id is not None}

    for activity in event.get("activity") or []:
        if not activity.get("hash"):
            continue
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


def _build_candidate_data(
    activity: dict[str, Any],
    chain: Chain,
    wallet: CuratedWallet,
) -> dict[str, Any]:
    """Build candidate event data dict for repository insertion."""
    value_usd = float(activity.get("value") or 0.0)
    log_obj = activity.get("log") or {}
    topics = log_obj.get("topics") or []
    event_type = _classify_event(topics, log_obj.get("address", "")) if topics else "TRANSFER"
    log_index = _hex_int(log_obj.get("logIndex"))
    chain_label = chain.label()

    raw_json = dict(activity)
    raw_json["value_usd"] = value_usd
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

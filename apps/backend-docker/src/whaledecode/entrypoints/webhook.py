"""FastAPI app with Telegram bot lifespan + Alchemy webhook endpoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.chain.normalizer import _classify_event, parse_token_amount
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.services.investigation import (
    build_investigation_service,
)
from whaledecode.config.alert_policy import policy_for
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.policies.sentinel import SentinelEngine
from whaledecode.domain.services.event_gate import (
    MIN_WHALE_THRESHOLD_USD,
    process_and_gate_candidate,
)
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.domain.value_objects.hash import Hash
from whaledecode.entrypoints.bot import build_telegram_app
from whaledecode.entrypoints.worker import launch_supervisor_tasks
from whaledecode.infrastructure.http import HttpClientManager
from whaledecode.infrastructure.telemetry import capture_exception, init_sentry
from whaledecode.services.decoder import TransactionDecoderService, apply_velocity_telemetry

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
    """FastAPI lifespan: start bot polling + consumer supervisor on startup, stop on shutdown.

    The bot + supervisor run in this same process, but their startup is bounded
    and failure-tolerant so it can never block uvicorn from binding — an outage
    in Telegram or the worker loop must not 502 inbound Alchemy webhooks.
    """
    # ``Settings`` is cheap to build at import time; only the DB/LLM service build
    # is deferred here so a connectivity failure surfaces at startup, not at import.
    global session_factory, _price_oracle
    init_sentry(settings)
    session_factory, investigation_service, _ = build_investigation_service(settings)
    _price_oracle = investigation_service._price_oracle
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.investigation_service = investigation_service

    async def _start_bot_and_supervisor() -> None:
        bot, dp = build_telegram_app(settings)
        app.state.bot = bot
        app.state.dp = dp
        stop_event = asyncio.Event()
        app.state.stop_event = stop_event
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.emit_startup()
        app.state.polling_task = asyncio.create_task(dp.start_polling(bot))
        app.state.supervisor_tasks = launch_supervisor_tasks(
            session_factory, investigation_service, settings, bot, stop_event
        )

    # Bound + tolerant: if the bot/supervisor can't start (Telegram down, bad
    # token, …) the web server still binds and serves webhooks.
    try:
        await asyncio.wait_for(_start_bot_and_supervisor(), timeout=15)
    except Exception as e:  # noqa: E501 - never let startup kill the web server
        logger.error("bot_supervisor_startup_failed", extra={"error": str(e)}, exc_info=True)

    # Daily active-rotation engine: reconcile the ≤300 monitored wallets with
    # Alchemy on startup, then every 24h. Skipped when credentials are absent so
    # local/dev runs don't error out.
    rotator_task = None
    if settings.ALCHEMY_API_KEY or settings.ALCHEMY_NOTIFY_TOKEN or settings.ALCHEMY_AUTH_TOKEN:
        if settings.ALCHEMY_WEBHOOK_ID or settings.ALCHEMY_WEBHOOK_ID_ETH:
            rotator_task = asyncio.create_task(_periodic_webhook_rotator(session_factory, settings))

    yield

    if rotator_task is not None:
        rotator_task.cancel()
        try:
            await rotator_task
        except asyncio.CancelledError:
            pass

    stop_event = getattr(app.state, "stop_event", None)
    if stop_event is not None:
        stop_event.set()
    polling_task = getattr(app.state, "polling_task", None)
    if polling_task is not None:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    supervisor_tasks = getattr(app.state, "supervisor_tasks", None) or []
    for task in supervisor_tasks:
        task.cancel()
    await asyncio.gather(*supervisor_tasks, return_exceptions=True)
    dp = getattr(app.state, "dp", None)
    if dp is not None:
        await dp.emit_shutdown()
    bot = getattr(app.state, "bot", None)
    if bot is not None:
        await bot.session.close()


async def _periodic_webhook_rotator(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Run the rotation cycle once on startup, then every 24h.

    Isolated in its own task; failures are logged and retried next cycle so a
    transient Alchemy/Postgres error never kills the web server.
    """
    from whaledecode.services.webhook_rotator import WebhookRotationService

    svc = WebhookRotationService(settings, session_factory)
    while True:
        try:
            summary = await svc.sync_rotation_cycle()
            logger.info("webhook_rotation_scheduled", extra=summary)
        except Exception as e:  # noqa: BLE001 - never crash the rotator loop
            logger.error(f"Scheduled webhook rotation error: {e}", exc_info=True)
        await asyncio.sleep(86400)  # 24 hours
    await HttpClientManager.aclose()


# ``settings`` is built at import time (cheap env config); the DB/LLM service
# factory is populated inside the lifespan so a connectivity failure surfaces at
# startup rather than crashing the import.
settings = Settings()
session_factory = None
_price_oracle = None

app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "WhaleDecode Webhook Receiver"}


@app.post("/webhook/alchemy")
async def alchemy_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_alchemy_signature: str = Header(None),
):
    # Fast-Ack gate: acknowledge in <50ms and never 401. Returning 200 on an
    # unauthenticated payload prevents Alchemy from retrying (and billing CU
    # per retry byte); the request is simply dropped.
    raw_body = await request.body()
    valid = verify_alchemy_signature(raw_body, x_alchemy_signature, settings.webhook_signing_keys)
    logger.info(
        "webhook_request",
        extra={"signature_present": bool(x_alchemy_signature), "signature_valid": valid},
    )
    if not valid:
        return {"status": "ignored", "reason": "invalid_signature"}

    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("webhook_malformed_json", extra={"error": str(exc)})
        return {"status": "ignored", "reason": "malformed_json"}

    background_tasks.add_task(
        TransactionDecoderService.process_payload, payload, settings, session_factory
    )
    return {"status": "accepted", "queued": True}


async def _process_webhook_payload(
    payload: dict[str, Any],
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Process webhook payload in background - only ingest and persist as pending.

    Runs after the HTTP 200 is already sent, so it can never slow the ack. Any
    failure is captured to Sentry and logged — never re-raised (a background task
    exception would otherwise just be logged by Starlette, with no retry).
    """
    try:
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

            # Per-chain ingestion gate: price the move now and only persist as
            # pending when it clears the chain's min_usd_threshold AND the global
            # value-noise floor (MIN_ALERT_USD_THRESHOLD).
            candidate_data = _build_candidate_data(activity, chain, wallet)
            if not await _clears_chain_floor(candidate_data, settings.MIN_ALERT_USD_THRESHOLD):
                logger.debug(
                    "webhook_dropped_below_alert_threshold",
                    extra={"dedupe_key": candidate_data["dedupe_key"]},
                )
                continue
            async with UnitOfWork(session_factory) as uow:
                await uow.candidate_events.create_pending(candidate_data)
                # Velocity telemetry: bump 30d tx count + decay penalty for both
                # sides (passive attribution needs no CU spend). Best-effort —
                # a telemetry failure must never block ingestion.
                try:
                    await apply_velocity_telemetry(
                        uow.session,
                        [activity.get("fromAddress"), activity.get("toAddress")],
                    )
                except Exception as exc:  # noqa: BLE001 - telemetry is non-critical
                    logger.warning("webhook_telemetry_failed", extra={"error": str(exc)})
                await uow.commit()
            logger.info("webhook_candidate_pending", extra={"dedupe_key": candidate_data["dedupe_key"]})
    except Exception as exc:  # noqa: BLE001 - background task must not crash silently
        logger.exception("webhook_process_failed", extra={"error": str(exc)})
        capture_exception(exc)


async def _clears_chain_floor(candidate_data: dict[str, Any], min_usd_threshold: float | None = None) -> bool:
    """True when the move prices above its chain's ingestion floor.

    Reuses the investigation gate's pricing so ingestion and investigation
    agree on value; the priced ``value_usd`` is written back into ``raw_json``
    so pending rows carry a real USD figure. Sub-floor moves never enter pending.

    ``min_usd_threshold`` (the ``MIN_ALERT_USD_THRESHOLD`` env control) lifts the
    effective floor to at least this global noise gate when supplied.
    """
    candidate = CandidateEvent(**candidate_data)
    await process_and_gate_candidate(candidate, _price_oracle)
    value_usd = float(candidate.raw_json.get("value_usd") or 0.0)
    candidate_data["raw_json"]["value_usd"] = value_usd
    policy = policy_for(candidate.chain)
    floor = policy.min_usd_threshold if policy else MIN_WHALE_THRESHOLD_USD
    if min_usd_threshold is not None:
        floor = max(floor, min_usd_threshold)
    if value_usd < floor:
        logger.info(
            "webhook_dropped_below_chain_floor",
            extra={"chain": candidate.chain, "value_usd": value_usd, "floor": floor},
        )
        return False
    return True


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

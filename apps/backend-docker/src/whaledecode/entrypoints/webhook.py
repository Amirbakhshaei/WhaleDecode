"""FastAPI app with Telegram bot lifespan (Alchemy webhook ingestion is
deprecated — on-chain data now arrives via the isolated Targeted Failover
Poller in ``whaledecode.entrypoints.poller``).

Telegram ingress is webhook-based (POST /webhook/telegram): stateless, so the
service scales horizontally behind Railway's load balancer with no getUpdates
409 conflicts."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from whaledecode.adapters.chain.normalizer import _classify_event, parse_token_amount
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
from whaledecode.entrypoints.bot import build_telegram_app, run_webhook
from whaledecode.entrypoints.worker import launch_supervisor_tasks
from whaledecode.infrastructure.telemetry import capture_exception, init_sentry

logger = logging.getLogger(__name__)

_sentinel = SentinelEngine()


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
    """FastAPI lifespan: conditionally start background supervisor on startup, stop on shutdown.

    When ``IS_WORKER=true`` (the default), this instance boots the full
    stack: Telegram bot, webhook registration, APScheduler cron jobs, and
    the Targeted Failover Poller.  When ``IS_WORKER=false`` the process
    only serves ``/health`` and webhook HTTP endpoints — no scheduler, no
    bot, no poller — so Railway replicas never duplicate cron jobs.
    """
    global session_factory, _price_oracle
    init_sentry(settings)
    app.state.settings = settings
    is_worker = settings.IS_WORKER
    logger.info("lifespan_start", is_worker=is_worker)

    async def _init_services() -> None:
        """Build DB + investigation service (needed by all instances for /health probe)."""
        global session_factory, _price_oracle
        factory, investigation_service, _ = build_investigation_service(settings)
        session_factory = factory
        _price_oracle = investigation_service._price_oracle
        app.state.session_factory = session_factory
        app.state.investigation_service = investigation_service

    async def _start_bot_and_supervisor() -> None:
        """Full worker startup: bot, Telegram webhook, scheduler, poller."""
        if getattr(app.state, "bot", None) is not None:
            logger.warning("bot_already_running_skipping_startup")
            return
        try:
            await _init_services()

            bot, dp = build_telegram_app(settings)
            app.state.bot = bot
            app.state.dp = dp
            # Channel probe — fail fast if Telegram destination is unreachable.
            channel_id = (
                settings.CHANNEL_CHAT_ID or settings.TELEGRAM_CHANNEL_ID or ""
            )
            if channel_id:
                try:
                    await bot.get_chat(channel_id)
                    logger.info("channel_probe_ok", extra={"channel_id": channel_id})
                except Exception as e:
                    logger.error(
                        "channel_probe_failed",
                        extra={"channel_id": channel_id, "error": str(e)},
                        exc_info=True,
                    )
                    capture_exception(e)
                    app.state.startup_failed = f"channel_probe_failed: {e}"
                    logger.critical("channel_probe_unreachable_crash", extra={"channel_id": channel_id})
                    os._exit(1)
            stop_event = asyncio.Event()
            app.state.stop_event = stop_event
            await dp.emit_startup()

            # Stateless Telegram webhook — only the worker registers it.
            webhook_url = settings.WEBHOOK_URL
            if not webhook_url:
                logger.critical(
                    "webhook_url_missing",
                    extra={"hint": "set WEBHOOK_URL (e.g. https://<railway-domain>) for serve mode"},
                )
                os._exit(1)
            secret = settings.WEBHOOK_SECRET.get_secret_value() if settings.WEBHOOK_SECRET else None
            full_url = webhook_url.rstrip("/") + "/webhook/telegram"
            await run_webhook(bot, dp, full_url, secret)
            app.state.bot_ready = True

            # APScheduler cron jobs + BackgroundAIWorker + alert loop
            app.state.supervisor_tasks = launch_supervisor_tasks(
                session_factory, app.state.investigation_service, settings, bot, stop_event
            )

            # Targeted Failover Poller — background task, reference kept to avoid GC.
            if settings.TARGETED_POLLER_ENABLED:
                from whaledecode.application.targeted_poller import TargetedPollerService

                poller_service = TargetedPollerService(session_factory, settings)
                app.state.poller_task = asyncio.create_task(poller_service.run(stop_event))
                app.state._poller_service = poller_service
                logger.info("targeted_poller_started")

            logger.info("bot_supervisor_started")
        except SystemExit:
            raise
        except BaseException as e:
            if isinstance(e, Exception):
                app.state.startup_failed = str(e)
                logger.error("bot_supervisor_startup_failed", extra={"error": str(e)}, exc_info=True)
                capture_exception(e)
            else:
                raise

    app.state.startup_task = asyncio.create_task(_start_bot_and_supervisor())

    yield

    # Teardown
    startup_task = getattr(app.state, "startup_task", None)
    if startup_task is not None and not startup_task.done():
        startup_task.cancel()
        try:
            await startup_task
        except asyncio.CancelledError:
            pass
    await asyncio.sleep(0)

    stop_event = getattr(app.state, "stop_event", None)
    if stop_event is not None:
        stop_event.set()
    supervisor_tasks = getattr(app.state, "supervisor_tasks", None) or []
    for task in supervisor_tasks:
        task.cancel()
    await asyncio.gather(*supervisor_tasks, return_exceptions=True)

    # Poller teardown
    poller_task = getattr(app.state, "poller_task", None)
    if poller_task is not None and not poller_task.done():
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass
    poller_service = getattr(app.state, "_poller_service", None)
    if poller_service is not None:
        await poller_service.aclose()

    dp = getattr(app.state, "dp", None)
    if dp is not None:
        await dp.emit_shutdown()
    bot = getattr(app.state, "bot", None)
    if bot is not None:
        await bot.session.close()


# ``settings`` is built at import time (cheap env config); the DB/LLM service
# factory is populated inside the lifespan so a connectivity failure surfaces at
# startup rather than crashing the import.
settings = Settings()
session_factory = None
_price_oracle = None

app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    startup_failed = getattr(app.state, "startup_failed", None)
    if startup_failed:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "service": "WhaleDecode Webhook Receiver",
                "bot_ready": False,
                "reason": "startup_failed",
                "detail": str(startup_failed)[:500],
            },
        )
    is_worker = settings.IS_WORKER
    startup_task = getattr(app.state, "startup_task", None)
    bot_ready = getattr(app.state, "bot_ready", False)

    if not is_worker:
        # Non-worker: no bot expected; healthy if startup didn't fail.
        sf = getattr(app.state, "session_factory", None) or globals().get("session_factory")
        if sf is not None:
            try:
                from sqlalchemy import text as _text
                async with sf() as _session:
                    await _session.execute(_text("SELECT 1"))
            except Exception as e:
                logger.error("health_db_probe_failed", extra={"error": str(e)}, exc_info=True)
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "degraded",
                        "service": "WhaleDecode Webhook Receiver",
                        "bot_ready": False,
                        "reason": "db_unreachable",
                        "detail": str(e)[:500],
                    },
                )
        return {
            "status": "ok",
            "service": "WhaleDecode Webhook Receiver",
            "bot_ready": False,
            "reason": "worker_disabled",
        }

    if not bot_ready:
        starting = startup_task is not None and not startup_task.done()
        if starting:
            return {
                "status": "ok",
                "service": "WhaleDecode Webhook Receiver",
                "bot_ready": False,
                "reason": "starting",
            }
        if startup_task is not None and startup_task.done():
            try:
                exc = startup_task.exception()
            except Exception:
                exc = None
            if exc is not None:
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "degraded",
                        "service": "WhaleDecode Webhook Receiver",
                        "bot_ready": False,
                        "reason": "startup_task_failed",
                        "detail": str(exc)[:500],
                    },
                )
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "service": "WhaleDecode Webhook Receiver",
                "bot_ready": False,
                "reason": "bot_not_running",
            },
        )
    # Optional DB probe
    sf = getattr(app.state, "session_factory", None) or globals().get("session_factory")
    if sf is not None:
        try:
            from sqlalchemy import text as _text
            async with sf() as _session:
                await _session.execute(_text("SELECT 1"))
        except Exception as e:
            logger.error("health_db_probe_failed", extra={"error": str(e)}, exc_info=True)
            return JSONResponse(
                status_code=503,
                content={
                    "status": "degraded",
                    "service": "WhaleDecode Webhook Receiver",
                    "bot_ready": True,
                    "reason": "db_unreachable",
                    "detail": str(e)[:500],
                },
            )
    return {
        "status": "ok",
        "service": "WhaleDecode Webhook Receiver",
        "bot_ready": True,
    }


@app.post("/webhook/telegram", include_in_schema=False)
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook and feed them into the dispatcher.

    Stateless: each request is independent, so any replica behind the load
    balancer can handle it (no getUpdates loop, no 409 conflicts).
    """
    secret = settings.WEBHOOK_SECRET.get_secret_value() if settings.WEBHOOK_SECRET else None
    if secret:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if provided != secret:
            logger.warning("telegram_webhook_bad_secret")
            return JSONResponse(status_code=403, content={"status": "forbidden"})
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "bad_json"})
    update = Update.model_validate(payload)
    bot = getattr(app.state, "bot", None)
    dp = getattr(app.state, "dp", None)
    if bot is None or dp is None:
        return JSONResponse(status_code=503, content={"status": "bot_not_ready"})
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.post("/webhook/alchemy", include_in_schema=False)
async def alchemy_webhook_deprecated():
    """Deprecation stub: ack 200 so Alchemy stops retrying, drop the payload.

    Ingestion now flows through the Targeted Failover Poller. Delete the
    webhooks in the Alchemy dashboard to stop deliveries entirely; until then
    this prevents 404 retry storms from burning anything downstream.
    """
    logger.info("webhook_deprecated_payload_dropped")
    return {"status": "deprecated", "reason": "use targeted_poller"}


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
            f"[FILTER_SKIP] Tx {str(candidate.tx_hash)[:10]}... | "
            f"Value ${value_usd:,.2f} < ${floor:,.2f} threshold"
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

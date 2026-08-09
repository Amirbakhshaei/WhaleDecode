"""Alchemy Address Activity webhook receiver.

Replaces the RPC pull loop: Alchemy pushes address activity for tracked wallets,
we HMAC-verify the delivery, re-shape each activity into a CandidateEvent, score
it with the SentinelEngine, and route qualifying events straight to the
investigation service (which dedupes + gates internally).
"""
import asyncio
import hashlib
import hmac
from typing import Any

import structlog
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.normalizer import _classify_event
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.application.services.investigation import (
    InvestigationService,
    build_investigation_service,
)
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.policies.sentinel import SentinelEngine
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.domain.value_objects.hash import Hash

log = structlog.get_logger()

_NETWORK_TO_CHAIN: dict[str, Chain] = {
    "ETH_MAINNET": Chain.ETH,
    "BASE_MAINNET": Chain.BASE,
    "ARB_MAINNET": Chain.ARB,
}

_sentinel = SentinelEngine()


def verify_alchemy_signature(signing_key: str, body: bytes, signature: str | None) -> bool:
    """Hex HMAC-SHA256 of the raw request body signed with the webhook signing key."""
    if not signature:
        return False
    digest = hmac.new(signing_key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest.encode(), signature.encode())


def _hex_int(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16)
        except ValueError:
            return default
    return default


def _activity_candidate(
    activity: dict[str, Any],
    chain: Chain,
    wallet: CuratedWallet,
) -> CandidateEvent:
    """Shape one Alchemy Address Activity into our internal candidate event."""
    # ponytail: Alchemy's `value` is the human-readable amount in the asset's own
    # unit (token count / ETH), not USD-priced. We reuse it as the existing
    # un-priced `value_usd` estimate; add a price feed if USD gating matters.
    value_usd = float(activity.get("value") or 0.0)
    log_obj = activity.get("log") or {}
    topics = log_obj.get("topics") or []
    event_type = _classify_event(topics, log_obj.get("address", "")) if topics else "TRANSFER"
    log_index = _hex_int(log_obj.get("logIndex"))
    chain_label = chain.label()

    raw_json = dict(activity)
    raw_json["value_usd"] = value_usd
    return CandidateEvent(
        wallet_id=wallet.id,
        chain=chain_label,
        tx_hash=Hash(activity["hash"]),
        log_index=log_index,
        block_number=_hex_int(activity.get("blockNum")),
        event_type=event_type,
        raw_json=raw_json,
        score=0.0,
        dedupe_key=f"{wallet.id}:{activity['hash']}:{log_index}",
    )


def _score_candidate(candidate: CandidateEvent) -> float:
    # ponytail: no accumulation/confluence terms — those need a recent-events DB
    # fetch per activity. Curated-wallet bonus keeps cherry files above the gate.
    return _sentinel.score(
        {
            "event_type": candidate.event_type,
            "value_usd": candidate.raw_json.get("value_usd", 0.0),
            "wallet_id": candidate.wallet_id,
            "tx_hash": str(candidate.tx_hash),
        },
        curated_wallet_ids={candidate.wallet_id},
    )


async def _safe_process(
    investigation_service: InvestigationService, candidate: CandidateEvent
) -> None:
    try:
        await investigation_service.process_event(candidate)
        log.info(
            "webhook_candidate_investigated",
            dedupe_key=candidate.dedupe_key,
            score=candidate.score,
        )
    except Exception as e:
        log.warning(
            "webhook_candidate_failed", dedupe_key=candidate.dedupe_key, error=str(e)
        )


async def _handle_alchemy(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    investigation_service: InvestigationService = request.app["investigation_service"]
    session_factory: async_sessionmaker[AsyncSession] = request.app["session_factory"]

    signing_key = (
        settings.ALCHEMY_WEBHOOK_SIGNING_KEY.get_secret_value()
        if settings.ALCHEMY_WEBHOOK_SIGNING_KEY
        else None
    )
    body = await request.read()
    signature = request.headers.get("x-alchemy-signature")
    if not signing_key or not verify_alchemy_signature(signing_key, body, signature):
        log.warning("webhook_invalid_signature", header_present=bool(signing_key))
        return web.Response(status=401, text="Invalid signature")

    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return web.Response(status=400, text="Invalid JSON body")

    if payload.get("type") != "ADDRESS_ACTIVITY":
        return web.Response(status=200, text="ignored")

    event = payload.get("event") or {}
    chain = _NETWORK_TO_CHAIN.get(event.get("network"))
    if chain is None:
        log.warning("webhook_unknown_network", network=event.get("network"))
        return web.Response(status=200, text="ignored")

    async with UnitOfWork(session_factory) as uow:
        wallets = await uow.curated_wallets.list_active(chain=chain.name)
    wallet_map = {w.address.lower(): w for w in wallets if w.id is not None}

    threshold = settings.ALERT_SCORE_THRESHOLD * 100
    for activity in event.get("activity") or []:
        if not activity.get("hash"):
            continue
        wallet = _match_wallet(activity, wallet_map)
        if wallet is None:
            continue

        candidate = _activity_candidate(activity, chain, wallet)
        candidate.score = _score_candidate(candidate)
        if candidate.score < threshold:
            continue

        asyncio.create_task(_safe_process(investigation_service, candidate))

    return web.Response(status=200, text="ok")


def _match_wallet(
    activity: dict[str, Any], wallet_map: dict[str, CuratedWallet]
) -> CuratedWallet | None:
    for side in ("fromAddress", "toAddress"):
        address = activity.get(side)
        if address and address.lower() in wallet_map:
            return wallet_map[address.lower()]
    return None


def _build_app(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    investigation_service: InvestigationService,
) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["session_factory"] = session_factory
    app["investigation_service"] = investigation_service
    app.router.add_post("/webhook/alchemy", _handle_alchemy)
    return app


async def run_webhook(settings: Settings) -> None:
    """Run the webhook HTTP server until cancelled. To be gathered alongside the bot."""
    session_factory, investigation_service, _ = build_investigation_service(settings)
    runner = web.AppRunner(_build_app(settings, session_factory, investigation_service))
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.PORT)
    await site.start()
    log.info("webhook_server_started", port=settings.PORT)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

"""Lazy Sentry telemetry.

Kept import-light so modules that capture exceptions at the top level never
hard-depend on ``sentry_sdk`` being installed: if the SDK is missing or not
initialized, ``capture_exception`` is a silent no-op.
"""
from __future__ import annotations

import logging

from whaledecode.config.settings import Settings

logger = logging.getLogger(__name__)

_INITIALIZED = False


def init_sentry(settings: Settings) -> None:
    """Initialize Sentry once, guarded by ``SENTRY_DSN``.

    ponytail: lazy import — a missing SDK must not crash process startup.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    dsn = settings.SENTRY_DSN
    if not dsn:
        logger.warning("sentry_disabled_no_dsn", exc_info=False)
        return
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry_disabled_no_sdk", exc_info=False)
        return
    sentry_sdk.init(
        dsn=dsn.get_secret_value(),
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.05,
    )
    _INITIALIZED = True


def capture_exception(exc: BaseException) -> None:
    """Send an exception to Sentry if initialized; otherwise do nothing."""
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        client = sentry_sdk.get_client()
        if client is None or client.dsn is None:
            return
    except Exception:
        # Fallback for older SDKs that still use Hub.
        try:
            if sentry_sdk.Hub.current.client is None:
                return
        except Exception:
            return
    sentry_sdk.capture_exception(exc)

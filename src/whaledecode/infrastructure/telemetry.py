"""Lazy Sentry telemetry.

Kept import-light so modules that capture exceptions at the top level never
hard-depend on ``sentry_sdk`` being installed: if the SDK is missing or not
initialized, ``capture_exception`` is a silent no-op.
"""
from __future__ import annotations

from whaledecode.config.settings import Settings

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
        return
    try:
        import sentry_sdk
    except ImportError:
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
    if sentry_sdk.Hub.current.client is None:
        return
    sentry_sdk.capture_exception(exc)

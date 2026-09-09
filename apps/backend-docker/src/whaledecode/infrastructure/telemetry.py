"""Lazy Sentry telemetry + production tracing primitives.

Kept import-light so modules that capture exceptions at the top level never
hard-depend on ``sentry_sdk`` being installed: if the SDK is missing or not
initialized, ``capture_exception`` is a silent no-op.

Also hosts the trace-context primitives (``trace_id`` correlation, URL
masking) used by every polling and ingestion log line so a single event
can be followed across processes via grep on the JSON ``trace_id`` field.
"""
from __future__ import annotations

import contextvars
import logging
import re
import sys
import uuid
from contextvars import ContextVar

import structlog

from whaledecode.config.settings import Settings

logger = logging.getLogger(__name__)

_INITIALIZED = False

# ponytail: process-global trace context. Every poll/worker pass sets a fresh
# trace_id so log lines emitted during the pass carry it. structlog's
# ``merge_contextvars`` reads it automatically — no manual kwarg needed.
trace_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "trace_context", default={}
)

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system-boot")


def bind_trace_id(_, __, event_dict):
    event_dict["trace_id"] = trace_id_var.get()
    return event_dict


def start_trace(trace_id: str | None = None) -> str:
    """Bind a new (or supplied) trace_id + span_id to the current context."""
    tid = (trace_id or uuid.uuid4().hex)[:12]
    trace_id_var.set(tid)
    # Keep legacy context in sync so existing callers of get_trace_id() work
    trace_context.set({"trace_id": tid, "span_id": uuid.uuid4().hex[:16]})
    return tid


def get_trace_id() -> str:
    # Prefer new var; fall back to legacy context
    val = trace_id_var.get()
    if val and val != "system-boot":
        return val
    return trace_context.get().get("trace_id", "trace-unset")


def inject_railway_message(_, __, event_dict):
    """
    Synthesizes a complete text representation into event_dict['message']
    so Railway's console and log downloads never render blank lines.
    """
    event = event_dict.get("event", "")
    kv_pairs = []
    for k, v in event_dict.items():
        if k in ("event", "level", "timestamp", "message", "msg"):
            continue
        kv_pairs.append(f"{k}={v}")
    formatted_text = f"{event} {' '.join(kv_pairs)}".strip()
    event_dict["message"] = formatted_text
    event_dict["msg"] = formatted_text
    return event_dict


def setup_telemetry():
    """
    Direct stdout JSON logging with guaranteed Railway message compatibility.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            bind_trace_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks,
            inject_railway_message,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


# ponytail: regex collapses any 16+ char token (after the first 8 chars) so
# an Alchemy ``/v2/alch_I3R1tBge7w-Y5EfwsITw8`` becomes ``alch_I3R***``.
# Catches /v2/<key>, /v3/<key>, ?dkey=<key>, /<secret-path>/<key>, etc.
_API_KEY_PATTERN = re.compile(r"([A-Za-z0-9_-]{8})[A-Za-z0-9_-]{16,}")


def mask_url(url: str) -> str:
    """Mask sensitive API keys in URLs before logging."""
    if not url:
        return ""
    return _API_KEY_PATTERN.sub(r"\1***", url)


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

import logging
import sys
import structlog
from whaledecode.config.settings import Settings


def setup_logging(settings: Settings) -> None:
    """
    Direct stdout JSON logging via PrintLoggerFactory.
    Eliminates the empty-string bug caused by Python stdlib logging formatters.
    Structlog formats JSON and writes directly to stdout — no stdlib middleware.
    """
    # 1. Reset root logger so third-party libs (uvicorn, httpx) don't stack handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    try:
        root_logger.setLevel(settings.LOG_LEVEL.upper())
    except Exception:
        root_logger.setLevel(logging.INFO)
        logging.getLogger(__name__).warning("invalid_log_level_fallback_to_info", extra={"log_level": settings.LOG_LEVEL})

    # 2. Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    for name in ("sqlalchemy.engine", "sqlalchemy.pool"):
        logging.getLogger(name).propagate = False

    from whaledecode.infrastructure.telemetry import format_railway_message

    # 3. Configure structlog with PrintLoggerFactory — writes JSON directly to stdout
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # picks up trace_context from telemetry.py
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.dict_tracebacks,
            format_railway_message,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

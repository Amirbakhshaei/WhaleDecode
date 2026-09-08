import logging
import sys
import structlog
from whaledecode.config.settings import Settings


def setup_logging(settings: Settings) -> None:
    """
    Configures structlog and standard library logging to output
    unified, pure JSON to sys.stdout without dropping message payloads.
    """
    # 1. Reset root logger and remove any existing misconfigured handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    # 2. Shared processors across structlog and third-party libraries (uvicorn, httpx)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.dict_tracebacks,
    ]

    # 3. Configure structlog to wrap events for the standard library formatter
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 4. Attach StreamHandler with ProcessorFormatter to the root logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processor=structlog.processors.JSONRenderer(),
        )
    )
    root_logger.addHandler(handler)

    # 5. Prevent uvicorn from overriding root handlers
    for uvicorn_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(uvicorn_logger)
        log.handlers.clear()
        log.propagate = True

    # 6. Silence raw SQLAlchemy polling/engine noise in production
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    # httpx logs one INFO line per RPC request — pure noise at poll cadence
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # 7. Single-owner loggers: propagate=False stops the duplicate multiline
    # streams that appear when a logger bubbles records into root while also
    # being handled elsewhere. App ("whaledecode.*") loggers intentionally keep
    # propagation — root is their only output handler.
    for name in ("sqlalchemy.engine", "sqlalchemy.pool"):
        logging.getLogger(name).propagate = False
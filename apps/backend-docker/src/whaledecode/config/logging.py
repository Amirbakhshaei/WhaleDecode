import logging
import sys

import structlog

from whaledecode.config.settings import Settings


def setup_logging(settings: Settings) -> None:
    # 1. Route stdlib (and therefore structlog's stdlib-backed) output to STDOUT
    #    so application logs are cleanly captured by container log collectors.
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.StreamHandler(sys.stdout))
    root.setLevel(settings.LOG_LEVEL.upper())
    # Keep stdlib formatting minimal — structlog already renders timestamp/level.
    for handler in root.handlers:
        handler.setFormatter(logging.Formatter("%(message)s"))

    # 2. Silence raw SQLAlchemy polling/engine noise in production.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.ENV == "dev"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

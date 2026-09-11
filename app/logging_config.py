"""Logging setup shared by the API, Celery worker and Beat.

Every log line, from our code and from libraries (uvicorn, Celery, SQLAlchemy),
goes to stdout as one JSON object. Set LOG_FORMAT=console for readable local output.
"""
import logging
import sys

import structlog

from app.config import LOG_FORMAT, LOG_LEVEL


def configure_logging() -> None:
    # Applied to every line, whether it came from structlog or the stdlib logging module
    shared_processors = [
        structlog.contextvars.merge_contextvars,  # task_id / request_id bound elsewhere
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if LOG_FORMAT == "console":
        final_processors = [structlog.dev.ConsoleRenderer()]
    else:
        final_processors = [
            structlog.processors.format_exc_info,  # traceback -> "exception" string field
            structlog.processors.JSONRenderer(),
        ]

    # structlog loggers hand their event dict to the stdlib handler below
    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,  # used for stdlib records (uvicorn, Celery, ...)
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *final_processors],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)

    # uvicorn installs its own handlers at startup; remove them so its lines use ours
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lib_logger = logging.getLogger(name)
        lib_logger.handlers = []
        lib_logger.propagate = True

    # SQL statements and per-request httpx lines are noise; our own events replace them
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
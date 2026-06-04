from __future__ import annotations

import logging
from typing import Any, Dict

import structlog


def configure_logging(service_name: str) -> None:
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Route stdlib logging records through structlog's JSON renderer.
    # This makes logger.info("event", extra={...}) emit a JSON line that
    # includes all extra fields alongside the event name.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    structlog.get_logger(service=service_name).info("logging_configured")


def log_event(logger: structlog.BoundLogger, event_type: str, payload: Dict[str, Any]) -> None:
    logger.info(event_type, **payload)


def get_logger(service_name: str) -> structlog.BoundLogger:
    return structlog.get_logger(service=service_name)

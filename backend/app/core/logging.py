import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.core.context import request_id_context, trace_id_context


def _add_context(
    _: Any,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    if request_id := request_id_context.get():
        event_dict["request_id"] = request_id
    if trace_id := trace_id_context.get():
        event_dict["trace_id"] = trace_id
    return event_dict


def configure_logging(level: str) -> None:
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s", force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)

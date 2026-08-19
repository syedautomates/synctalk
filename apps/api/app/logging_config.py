"""Structured JSON logging with request/job IDs (claude.md M7).

Any log call anywhere in the app (services, routes) automatically gets `request_id`
stamped onto it via a contextvar + logging.Filter, without threading a request_id
parameter through every function signature -- contextvars propagate correctly through
FastAPI's per-request asyncio task. `job_id` (and any other field) is attached the
ordinary way via `extra={...}` at call sites that have it (jobs.py, routes/internal.py).
"""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Every attribute a stdlib LogRecord carries by default -- anything else on the record
# is either our contextvar-injected request_id or an explicit `extra={...}` field, and
# gets included in the JSON payload automatically. Keeps this formatter generic instead
# of hardcoding a fixed field list that call sites have to know about.
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = request_id_var.get()
        if request_id is not None and not hasattr(record, "request_id"):
            record.request_id = request_id
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn's own loggers otherwise bypass this handler with their default plain-text
    # formatting -- route them through the same JSON handler for consistent log output.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

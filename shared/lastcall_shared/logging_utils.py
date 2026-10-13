"""Logging utilities for Cloud Logging compatibility and PII protection."""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

from lastcall_shared.buyer_keys import mask_phone  # one masking rule for logs and the page

# Pattern matching Pakistani mobiles, Pakistani landlines (Karachi 021, Lahore 042, etc.),
# un-prefixed 92 numbers, and international E.164 formats (+...).
# Plain IDs (mart_khi_001) and ISO timestamps (2026-10-06T18:00:00Z) are not matched.
PHONE_PATTERN = re.compile(
    r"(?:\+?92[\s\-]?|0)3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}|"
    r"(?:\+?92[\s\-]?|0)(?:21|42|51|41|52|61|71|81|91|[2-9]\d{2})[\s\-]?\d{3,4}[\s\-]?\d{4}|"
    r"\+[1-9]\d{6,14}"
)


def mask_pii_in_text(text: str) -> str:
    """Finds phone numbers in a string and masks them."""

    def _repl(match: re.Match[str]) -> str:
        matched = match.group(0)
        return mask_phone(matched)

    return PHONE_PATTERN.sub(_repl, text)


def mask_pii_data(data: Any) -> Any:
    """Recursively masks PII in strings, dicts, and lists."""
    if isinstance(data, str):
        return mask_pii_in_text(data)
    elif isinstance(data, dict):
        return {k: mask_pii_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_pii_data(item) for item in data]
    return data


class CloudLoggingJsonFormatter(logging.Formatter):
    """Formats log records as JSON objects compatible with Google Cloud Logging."""

    def __init__(self, service_name: str = "last-call"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        # Map standard python levels to Cloud Logging severities
        severity_map = {
            logging.DEBUG: "DEBUG",
            logging.INFO: "INFO",
            logging.WARNING: "WARNING",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "CRITICAL",
        }
        severity = severity_map.get(record.levelno, "DEFAULT")

        # Mask PII in the log message
        raw_msg = record.getMessage()
        masked_msg = mask_pii_in_text(raw_msg)

        payload: dict[str, Any] = {
            "severity": severity,
            "message": masked_msg,
            "serviceContext": {"service": self.service_name},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Recursively mask custom extra attributes if present
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelno",
            "levelname",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "extra_fields",
            "taskName",
        }
        for k, v in record.__dict__.items():
            if k not in standard_attrs and not k.startswith("_"):
                payload[k] = mask_pii_data(v)

        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            for k, v in record.extra_fields.items():
                payload[k] = mask_pii_data(v)

        if record.exc_info:
            raw_exc = self.formatException(record.exc_info)
            payload["exception"] = mask_pii_in_text(raw_exc)

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_structured_logging(service_name: str = "last-call", level: int = logging.INFO) -> logging.Logger:
    """Configures the root logger and uvicorn loggers to output structured JSON to stdout."""
    formatter = CloudLoggingJsonFormatter(service_name=service_name)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to prevent duplicate output
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)

    # Configure uvicorn loggers so error tracebacks and messages are masked and structured JSON (R4)
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(handler)
        uv_logger.propagate = False

    return root_logger

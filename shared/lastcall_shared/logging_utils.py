"""Logging utilities for Cloud Logging compatibility and PII protection."""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

# Pattern matching Pakistani and international phone numbers
PHONE_PATTERN = re.compile(
    r"(?:\+?92|0)?(?:3\d{2})[\s\-]?\d{3}[\s\-]?\d{4}|\+?[1-9]\d{1,14}"
)


def mask_phone(phone: str) -> str:
    """Masks a phone number, preserving the first 4-5 chars and last 2 digits."""
    cleaned = phone.strip()
    if len(cleaned) < 7:
        return "***"
    prefix = cleaned[:5]
    suffix = cleaned[-2:]
    masked_middle = "*" * (len(cleaned) - 7)
    return f"{prefix}{masked_middle}{suffix}"


def mask_pii_in_text(text: str) -> str:
    """Finds phone numbers in a string and masks them."""
    def _repl(match: re.Match[str]) -> str:
        matched = match.group(0)
        # Skip purely numeric strings that are too short to be phone numbers
        if len(matched.replace("-", "").replace(" ", "").replace("+", "")) < 8:
            return matched
        return mask_phone(matched)

    return PHONE_PATTERN.sub(_repl, text)


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

        # Include custom extra attributes if present
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            for k, v in record.extra_fields.items():
                if isinstance(v, str):
                    payload[k] = mask_pii_in_text(v)
                else:
                    payload[k] = v

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_structured_logging(service_name: str = "last-call", level: int = logging.INFO) -> logging.Logger:
    """Configures the root logger to output structured JSON to stdout."""
    logger = logging.getLogger()
    logger.setLevel(level)

    # Remove existing handlers to prevent duplicate output
    for h in list(logger.handlers):
        logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingJsonFormatter(service_name=service_name))
    logger.addHandler(handler)
    return logger

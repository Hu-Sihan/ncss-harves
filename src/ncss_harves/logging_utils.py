from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping


SENSITIVE_PARTS = (
    "password",
    "passwd",
    "cookie",
    "token",
    "credential",
    "authorization",
    "username",
    "account",
    "service_ticket",
)


def _sensitive(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_PARTS)


def redact(value: Any, *, key: object = "") -> Any:
    if key and _sensitive(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {item_key: redact(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[REDACTED_PHONE]", value)
        value = re.sub(
            r"(?i)\b(password|passwd|cookie|authorization|token|service[_ -]?ticket)"
            r"\s*[:=]\s*[^\s,;]+",
            lambda match: f"{match.group(1)}=[REDACTED]",
            value,
        )
    return value


class SafeLogger:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    @staticmethod
    def _message(message: str, fields: Mapping[str, Any]) -> str:
        safe = redact(fields)
        suffix = " ".join(
            f"{key}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
            for key, value in safe.items()
        )
        return f"{message} {suffix}".rstrip()

    def debug(self, message: str, **fields: Any) -> None:
        self.logger.debug(self._message(message, fields))

    def info(self, message: str, **fields: Any) -> None:
        self.logger.info(self._message(message, fields))

    def warning(self, message: str, **fields: Any) -> None:
        self.logger.warning(self._message(message, fields))

    warn = warning

    def error(self, message: str, **fields: Any) -> None:
        self.logger.error(self._message(message, fields))

    def exception(self, message: str, **fields: Any) -> None:
        self.logger.exception(self._message(message, fields))


class LevelColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[37m",
        logging.INFO: "\033[37m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[31m",
    }

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        color = self.COLORS.get(record.levelno, "\033[37m")
        return f"{color}{rendered}\033[0m"


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def formatter_for_stream(stream: Any) -> logging.Formatter:
    try:
        interactive = bool(stream.isatty())
    except (AttributeError, OSError):
        interactive = False
    formatter_type = LevelColorFormatter if interactive else logging.Formatter
    return formatter_type(LOG_FORMAT, LOG_DATE_FORMAT)


def configure_logging(level: int = logging.INFO) -> SafeLogger:
    logger = logging.getLogger("ncss_harves")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter_for_stream(handler.stream))
        logger.addHandler(handler)
        logger.propagate = False
    return SafeLogger(logger)

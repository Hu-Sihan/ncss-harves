from __future__ import annotations

import logging

from ncss_harves.logging_utils import LevelColorFormatter, SafeLogger, formatter_for_stream, redact


def test_sensitive_values_are_redacted(caplog) -> None:
    logger = SafeLogger(logging.getLogger("ncss_harves.test.safe"))
    with caplog.at_level(logging.ERROR):
        logger.error(
            "login failed",
            password="secret-value",
            cookie="token-value",
            username="visible-account",
        )

    assert "secret-value" not in caplog.text
    assert "token-value" not in caplog.text
    assert "visible-account" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_nested_sensitive_values_are_redacted() -> None:
    result = redact({"params": {"jobName": "产品", "Cookie": "secret"}, "jobs": ["safe"]})
    assert result == {"params": {"jobName": "产品", "Cookie": "[REDACTED]"}, "jobs": ["safe"]}


def test_phone_and_embedded_auth_values_are_redacted() -> None:
    result = redact("手机号 13800138000 Cookie=session-secret token=short-secret")
    assert "13800138000" not in result
    assert "session-secret" not in result
    assert "short-secret" not in result


def test_color_is_only_enabled_for_interactive_streams() -> None:
    class Stream:
        def __init__(self, interactive: bool) -> None:
            self.interactive = interactive

        def isatty(self) -> bool:
            return self.interactive

    assert isinstance(formatter_for_stream(Stream(True)), LevelColorFormatter)
    assert not isinstance(formatter_for_stream(Stream(False)), LevelColorFormatter)


def test_query_log_contains_counts_but_not_payload(caplog) -> None:
    logger = SafeLogger(logging.getLogger("ncss_harves.test.query"))
    with caplog.at_level(logging.INFO):
        logger.info("query", params={"offset": 1}, returned=2, total=10)
    assert "returned=2" in caplog.text
    assert "total=10" in caplog.text

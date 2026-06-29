"""Structured logging with bearer-token redaction (NFR-6 / SEC-2)."""

from __future__ import annotations

import logging
import re

# Matches "Bearer <token>" (case-insensitive). The token is any run of
# non-whitespace characters, so redaction is robust to arbitrary token charsets
# (not just ASCII) — defense-in-depth so secrets never reach logs.
_BEARER = re.compile(r"(?i)(bearer\s+)(\S+)")


def redact(text: str) -> str:
    """Scrub bearer tokens from a string so secrets never reach logs."""
    if not text:
        return text
    return _BEARER.sub(r"\1[REDACTED]", text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True


def get_logger(name: str = "caduceus") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        handler.addFilter(RedactionFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

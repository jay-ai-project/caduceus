"""PURE name validation + sandbox naming (BR-A1, BR-A2)."""

from __future__ import annotations

import re

from caduceus.common.errors import invalid_request_error

SANDBOX_PREFIX = "cad-"
MAX_NAME_LEN = 50
_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")  # sbx-compatible


def validate_name(name: str) -> str:
    """Return the normalized (trimmed) name or raise ProxyError(400)."""
    n = (name or "").strip()
    if not n:
        raise invalid_request_error("Agent name must not be empty")
    if len(n) > MAX_NAME_LEN:
        raise invalid_request_error(f"Agent name too long (max {MAX_NAME_LEN})")
    if not _NAME_RE.match(n):
        raise invalid_request_error(
            "Agent name may contain only letters, digits, and '.', '_', '+', '-'"
        )
    return n


def sandbox_name(name: str) -> str:
    """Map a (validated) agent name to its sbx sandbox name."""
    return SANDBOX_PREFIX + name

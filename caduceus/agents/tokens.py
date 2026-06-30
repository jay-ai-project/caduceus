"""Token minting (BR-A4): cryptographically-random per-agent credentials."""

from __future__ import annotations

import secrets

#: minimum acceptable token length (urlsafe base64 of >=32 bytes ~ 43 chars)
MIN_TOKEN_LEN = 32


def mint_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

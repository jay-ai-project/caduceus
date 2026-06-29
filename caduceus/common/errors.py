"""Normalized proxy errors mapped to the OpenAI error JSON shape."""

from __future__ import annotations


class ProxyError(Exception):
    """An error that can be rendered as an OpenAI-compatible error response.

    `to_openai()` yields `{"error": {"message", "type", "code"}}`.
    """

    def __init__(self, http_status: int, type: str, message: str, code: str | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.type = type
        self.message = message
        self.code = code

    def to_openai(self) -> dict:
        return {"error": {"message": self.message, "type": self.type, "code": self.code}}


def authentication_error(message: str = "Missing or invalid API key") -> ProxyError:
    return ProxyError(401, "authentication_error", message)


def invalid_request_error(message: str) -> ProxyError:
    return ProxyError(400, "invalid_request_error", message)


def upstream_error(message: str, status: int = 502) -> ProxyError:
    return ProxyError(status, "upstream_error", message)


def timeout_error(message: str = "Upstream request timed out") -> ProxyError:
    return ProxyError(504, "timeout_error", message)

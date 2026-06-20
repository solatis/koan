# Pure error classification and backoff for transient provider errors.
#
# classify_provider_error determines whether an exception is worth retrying
# (transient) or should propagate immediately (unexpected/fail-fast).
#
# compute_backoff_seconds implements exponential backoff with a ceiling so
# the caller knows how long to sleep before the next attempt.
#
# Both functions are pure (no I/O, no state) so they are easy to unit-test
# and safe to call from any async context.

from __future__ import annotations

from typing import Literal


# HTTP status codes that indicate a transient provider condition worth retrying.
# 401/403 are included because some providers return them transiently under
# load or token-bucket exhaustion before issuing a 429.
TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 401, 403})


def classify_provider_error(err: BaseException) -> Literal["transient", "unexpected"]:
    """Classify a provider exception as transient (retry) or unexpected (fail-fast).

    Transient conditions:
      - asyncio.TimeoutError: request timed out waiting for the provider.
      - httpx.TimeoutException and subclasses: connect/read/write/pool timeouts.
      - httpx.ConnectError: TCP-level connection refused or reset.
      - httpx.RemoteProtocolError: server closed or spoke invalid HTTP.
      - pydantic_ai.exceptions.ModelHTTPError with status_code in TRANSIENT_STATUS_CODES.

    Everything else is unexpected: unknown errors fail fast so they are not
    silently swallowed by the retry loop.
    """
    import asyncio

    import httpx
    from pydantic_ai.exceptions import ModelHTTPError

    if isinstance(err, asyncio.TimeoutError):
        return "transient"
    if isinstance(err, httpx.TimeoutException):
        return "transient"
    if isinstance(err, (httpx.ConnectError, httpx.RemoteProtocolError)):
        return "transient"
    if isinstance(err, ModelHTTPError):
        if err.status_code in TRANSIENT_STATUS_CODES:
            return "transient"
    return "unexpected"


def compute_backoff_seconds(attempt: int, cap_seconds: float, base: float = 1.0) -> float:
    """Exponential backoff with ceiling.

    Returns min(base * 2**attempt, cap_seconds).

    attempt is 1-based (incremented before this call):
      attempt=1 -> base * 2  = 2s
      attempt=2 -> base * 4  = 4s
      attempt=10 -> capped at cap_seconds

    Args:
        attempt: Current retry attempt number (1-based).
        cap_seconds: Maximum backoff ceiling in seconds.
        base: Base multiplier (default 1.0).
    """
    return min(base * (2 ** attempt), cap_seconds)

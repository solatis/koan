# Pure error classification and backoff for provider errors.
#
# classify_provider_error determines whether an exception is worth retrying
# (transient) or should propagate immediately (unexpected/fail-fast).
#
# The classification is a fail-fast denylist: only programming errors and
# cancellation/exit signals propagate; everything else -- every ModelHTTPError
# status code, connection failures, parse errors, unknown exceptions -- is
# retried. A wasted retry cycle that eventually escalates to the user is far
# less disruptive than a fail-fast that destroys the whole workflow run.
#
# compute_backoff_seconds implements exponential backoff with a ceiling so
# the caller knows how long to sleep before the next attempt.
#
# Both functions are pure (no I/O, no state) so they are easy to unit-test
# and safe to call from any async context.

from __future__ import annotations

from typing import Literal


# Programming errors: a retry cannot fix a bug in the code, so these fail
# fast with a full traceback instead of being silently absorbed by the retry
# loop. ValueError is deliberately absent -- json.JSONDecodeError subclasses
# it, and a truncated stream from an overloaded provider surfaces as exactly
# that.
PROGRAMMING_ERRORS: tuple[type[Exception], ...] = (
    TypeError,
    AttributeError,
    NameError,
    KeyError,
    IndexError,
    AssertionError,
    NotImplementedError,
)


def classify_provider_error(err: BaseException) -> Literal["transient", "unexpected"]:
    """Classify a provider exception as transient (retry) or unexpected (fail-fast).

    Fail-fast (unexpected):
      - Non-Exception BaseExceptions (asyncio.CancelledError, KeyboardInterrupt,
        SystemExit, GeneratorExit): intentional control flow, never retried.
        The retry loop catches BaseException, so this guard is load-bearing
        for task cancellation.
      - PROGRAMMING_ERRORS: bugs in the code; retrying cannot help.
      - pydantic_ai.exceptions.UserError: pydantic-ai misconfiguration, which
        is a programming error on our side.

    Everything else is transient and retried -- all ModelHTTPError status
    codes (including 400s), httpx errors, timeouts, ValueError, RuntimeError,
    and unknown exceptions. Persistent failures still surface: the retry loop
    escalates to the user once the attempt budget is exhausted.
    """
    from pydantic_ai.exceptions import UserError

    if not isinstance(err, Exception):
        return "unexpected"
    if isinstance(err, PROGRAMMING_ERRORS):
        return "unexpected"
    if isinstance(err, UserError):
        return "unexpected"
    return "transient"


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

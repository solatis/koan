# Runtime fail-fast guard for prompt-cache effectiveness.
#
# Rationale: a silent cache miss on a caching-capable route re-sends the full
# input at full price every turn, which can burn budget rapidly without any
# visible error. This module observes cumulative cache_read_tokens across turns
# and raises AgentError when substantial input has been re-sent across two or
# more requests yet no cache reads have occurred.
#
# The guard is absolute-zero: it fires only when cache_read_tokens is exactly
# zero across the whole run to date. It disarms permanently once any cache read
# is observed and does not detect mid-run regressions after caching has worked.
# This is intentional: the dominant failure class is "caching never started",
# not "caching stopped mid-run".

from __future__ import annotations

from .base import AgentDiagnostic, AgentError
from .model_catalog import cache_read_expected

# Minimum number of model requests before the guard fires.
# Two requests means the prefix has been re-sent at least once, which is the
# earliest point a cache read could appear. Single-request scouts that never
# re-send are exempt by this gate.
CACHE_GUARD_MIN_REQUESTS: int = 2

# Minimum accumulated input tokens before the guard fires.
# 50 000 tokens is well above Anthropic's 1024-token cache minimum and Haiku's
# 4096-token minimum, so small prefixes that legitimately miss do not raise.
# A provider's per-request minimum is tolerated as a low-cost miss (brief D3).
CACHE_GUARD_MIN_INPUT_TOKENS: int = 50_000


def check_cache_effectiveness(
    provider: str,
    model: str,
    caching_mode: str,
    cumulative_input_tokens: int,
    cumulative_cache_read_tokens: int,
    cumulative_requests: int,
) -> None:
    """Raise AgentError when a caching-expected route shows zero cache reads at volume.

    Early-return conditions (no raise):
      - caching_mode == "off": caching deliberately disabled; nothing to check.
      - cache_read_expected(provider, model) is False: route is not cache-expected
        (OpenRouter, Voyage, Bedrock-Nova, or unknown provider).
      - cumulative_requests < CACHE_GUARD_MIN_REQUESTS: warmup; the prefix has
        not yet been re-sent, so zero cache reads are expected.
      - cumulative_input_tokens < CACHE_GUARD_MIN_INPUT_TOKENS: prefix is small
        enough to fall below provider cache minimums; tolerated as a low-cost miss.
      - cumulative_cache_read_tokens > 0: caching is working; disarm permanently.

    Trip condition (raises AgentError with code "prompt_cache_ineffective"):
      All early-return conditions are False and cache_read_tokens is still zero.
      This signals a logic error (wrong keys, prefix instability, transport
      silently ignoring a cache setting) that risks rapid budget burn.

    Args:
        provider: koan transport type (e.g. "anthropic", "bedrock", "google").
        model: resolved model id (e.g. "claude-sonnet-4-5").
        caching_mode: CachingPolicy.mode string ("auto" or "off").
        cumulative_input_tokens: total input tokens accumulated across turns so far.
        cumulative_cache_read_tokens: total cache_read_tokens accumulated so far.
        cumulative_requests: total model requests accumulated across turns so far.
    """
    if caching_mode == "off":
        return

    if not cache_read_expected(provider, model):
        return

    if cumulative_requests < CACHE_GUARD_MIN_REQUESTS:
        return

    if cumulative_input_tokens < CACHE_GUARD_MIN_INPUT_TOKENS:
        return

    if cumulative_cache_read_tokens > 0:
        return

    raise AgentError(AgentDiagnostic(
        code="prompt_cache_ineffective",
        agent=provider,
        stage="run_agent_loop",
        message=(
            f"Prompt caching produced zero cache reads for {provider}/{model} "
            f"after {cumulative_requests} requests and {cumulative_input_tokens} "
            f"input tokens. Caching is expected on this route; a silent miss risks "
            f"rapid budget burn. Check the cacheable-prefix byte-stability and the "
            f"emitted cache settings."
        ),
    ))

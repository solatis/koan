# Byte-wise bounding of tool results.
#
# Record-count limits (DEFAULT_LIMIT in builtin_tools.py) bound how many
# lines/matches/paths a tool returns, but a single record can be arbitrarily
# large: a grep over koan/koan once matched two single-line sourcemaps
# (5.2 MB + 1.8 MB) under koan/web/static/app/assets/, producing a 7 MB tool
# result that permanently poisoned the message history -- every subsequent
# provider request failed HTTP 400 "prompt too long". Byte budgets close that
# gap (see docs/tool-output-limits.md).
#
# Two layers, two constants:
#
#   DEFAULT_TOOL_RESULT_MAX_BYTES -- the in-tool cumulative budget. Streaming
#     tools (grep/bash/glob) count bytes as records are collected and stop
#     processing (stop reading files, kill the subprocess) once the budget is
#     exhausted: an execution bound, not just a size bound.
#
#   TOOL_RESULT_CEILING_BYTES -- the ByteBudgetToolset ceiling applied to
#     every result of the builtin (untrusted) toolset. A safety net above the
#     in-tool budget: catches accounting slack (headers, truncation notes)
#     and tools without their own byte bound (web_fetch's char cap can be
#     4x its size in UTF-8 bytes). Trusted koan_* tools are exempt -- they
#     are bound by construction (docs/tool-output-limits.md).
#
# The primitives compose transducer-style: ByteBudget is the stateful
# accumulator (pull-based loops like bash's select loop), take_within_budget
# wraps it across a record iterator (push-through loops like grep's).

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

# AbstractToolset must be importable FROM THIS MODULE by name: WrapperToolset's
# `wrapped: AbstractToolset[AgentDepsT]` field annotation is a string (PEP 563),
# and beartype (active under `koan run --debug` via beartype_package) resolves
# it against the namespace of the module defining the dataclass-generated
# __init__ -- this one. Without the import, every ByteBudgetToolset(...) call
# raises BeartypeCallHintForwardRefException in the app while passing in tests
# (pytest runs without the claw hook).
from pydantic_ai.toolsets import AbstractToolset, WrapperToolset

__all__ = [
    "DEFAULT_TOOL_RESULT_MAX_BYTES",
    "TOOL_RESULT_CEILING_BYTES",
    "AbstractToolset",
    "ByteBudget",
    "ByteBudgetToolset",
    "budget_suffix",
    "ceiling_suffix",
    "take_within_budget",
    "truncate_to_budget",
]

DEFAULT_TOOL_RESULT_MAX_BYTES: int = 32 * 1024
TOOL_RESULT_CEILING_BYTES: int = 2 * DEFAULT_TOOL_RESULT_MAX_BYTES


def budget_suffix(max_bytes: int) -> str:
    """In-tool truncation marker: names the budget and how to react."""
    return (
        f"... [truncated: output exceeded {max_bytes} byte budget"
        " -- narrow the pattern, path, or command]"
    )


def ceiling_suffix(max_bytes: int) -> str:
    """Wrapper-ceiling truncation marker, distinct from the in-tool one so
    transcripts show which layer fired."""
    return f"... [truncated: tool result exceeded {max_bytes} byte ceiling]"


def truncate_to_budget(s: str, max_bytes: int, suffix: str) -> str:
    """Truncate `s` so that its UTF-8 encoding fits within `max_bytes`.

    Identity when `s` already fits. Otherwise the string is byte-sliced at
    (max_bytes - suffix bytes) and decoded with errors="ignore" -- a split
    codepoint at the cut is dropped cleanly -- then `suffix` is appended.
    The result, including the suffix, always encodes to <= max_bytes.

    Degenerate case: when max_bytes cannot even hold the suffix, the bare
    byte-sliced string is returned without a suffix (never raises).
    """
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    keep = max_bytes - len(suffix.encode("utf-8"))
    if keep <= 0:
        return encoded[: max(max_bytes, 0)].decode("utf-8", errors="ignore")
    return encoded[:keep].decode("utf-8", errors="ignore") + suffix


class ByteBudget:
    """Cumulative UTF-8 byte counter for a joiner-delimited record stream.

    Counts what the final `joiner.join(records)` will encode to: each record
    after the first costs its own bytes plus the joiner's. `add` either
    accepts a record (True) or marks the budget exhausted (False); `clip`
    then renders the rejected record's prefix that still fits, ending in the
    budget_suffix marker. `clip` does not mutate -- exhaustion is recorded by
    the failing `add`.
    """

    def __init__(self, max_bytes: int, joiner: str = "\n"):
        self._max = max_bytes
        self._joiner_cost = len(joiner.encode("utf-8"))
        self._used = 0
        self._count = 0
        self._exhausted = False

    def add(self, item: str) -> bool:
        cost = len(item.encode("utf-8")) + (self._joiner_cost if self._count else 0)
        if self._used + cost > self._max:
            self._exhausted = True
            return False
        self._used += cost
        self._count += 1
        return True

    def clip(self, item: str) -> str:
        available = self.remaining - (self._joiner_cost if self._count else 0)
        return truncate_to_budget(item, max(available, 0), budget_suffix(self._max))

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def remaining(self) -> int:
        return max(self._max - self._used, 0)


def take_within_budget(items: Iterable[str], budget: ByteBudget) -> Iterator[str]:
    """Yield records from `items` while `budget` accepts them.

    On the first record that does not fit, yield its clipped form (when
    nonempty) and stop -- WITHOUT pulling further from `items`. Wrapped
    around a lazy source (grep's match generator) this is an execution
    bound: the source stops being consumed the moment the budget fills.
    Callers check `budget.exhausted` afterward to append a truncation note.
    """
    for item in items:
        if budget.add(item):
            yield item
            continue
        clipped = budget.clip(item)
        if clipped:
            yield clipped
        return


@dataclass
class ByteBudgetToolset(WrapperToolset[Any]):
    """Ceiling on every string result of the wrapped toolset.

    Must stay a dataclass: WrapperToolset.for_run/for_run_step rebuild the
    wrapper via dataclasses.replace(self, wrapped=...). Non-string results
    pass through unchanged; exceptions propagate.
    """

    max_bytes: int = TOOL_RESULT_CEILING_BYTES

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: Any, tool: Any) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)
        if isinstance(result, str):
            return truncate_to_budget(result, self.max_bytes, ceiling_suffix(self.max_bytes))
        return result

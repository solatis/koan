# Unit tests for koan.tools.byte_budget.
#
# Pure layer only -- no filesystem, no network, no agent loop. The
# ByteBudgetToolset tests use a minimal AbstractToolset stand-in via
# FunctionToolset so call_tool goes through the real pydantic-ai plumbing.
#
# Coverage:
# - truncate_to_budget: identity under budget, hard <= max_bytes guarantee
#   including suffix, suffix only when truncated, multibyte boundary safety,
#   degenerate tiny budgets
# - ByteBudget: acceptance under budget, exact joiner accounting, exhaustion
#   on the first overflowing record, clip keeps the record prefix
# - take_within_budget: passthrough under budget, clipped tail record,
#   early termination (source not pulled after exhaustion)
# - ByteBudgetToolset: over-ceiling truncation, short passthrough, non-str
#   passthrough, dataclasses.replace round-trip (the for_run contract)

from __future__ import annotations

import dataclasses

import pytest

from koan.tools.byte_budget import (
    DEFAULT_TOOL_RESULT_MAX_BYTES,
    TOOL_RESULT_CEILING_BYTES,
    ByteBudget,
    ByteBudgetToolset,
    budget_suffix,
    ceiling_suffix,
    take_within_budget,
    truncate_to_budget,
)


# -- truncate_to_budget -------------------------------------------------------- #


def test_truncate_identity_under_budget():
    s = "hello world"
    assert truncate_to_budget(s, 100, "... [truncated]") is s


def test_truncate_result_fits_budget_including_suffix():
    s = "x" * 1000
    out = truncate_to_budget(s, 100, "... [truncated]")
    assert len(out.encode("utf-8")) <= 100
    assert out.endswith("... [truncated]")
    assert out.startswith("x")


def test_truncate_suffix_only_when_truncated():
    s = "x" * 50
    assert "[truncated" not in truncate_to_budget(s, 100, "... [truncated]")


def test_truncate_multibyte_boundary_is_clean():
    # 2-byte codepoints: an odd byte budget forces a split mid-codepoint.
    s = "é" * 1000
    out = truncate_to_budget(s, 101, "!")
    assert len(out.encode("utf-8")) <= 101
    assert out.endswith("!")
    # The kept prefix decodes cleanly and is a char-prefix of the input.
    assert s.startswith(out[:-1])


def test_truncate_cjk_boundary_is_clean():
    s = "世界" * 500  # 3-byte codepoints
    out = truncate_to_budget(s, 100, "...")
    assert len(out.encode("utf-8")) <= 100
    assert s.startswith(out[:-3])


def test_truncate_degenerate_budget_smaller_than_suffix():
    out = truncate_to_budget("abcdef" * 10, 4, "... [truncated]")
    assert out == "abcd"


# -- ByteBudget ---------------------------------------------------------------- #


def test_budget_accepts_records_that_fit():
    b = ByteBudget(100)
    assert b.add("aaaa")
    assert b.add("bbbb")
    assert not b.exhausted


def test_budget_counts_joiner_bytes_exactly():
    items = ["aa", "bbb", "c"]
    joined_bytes = len("\n".join(items).encode("utf-8"))
    b = ByteBudget(joined_bytes)
    assert all(b.add(i) for i in items)
    assert b.remaining == 0
    # One more byte does not fit.
    assert not b.add("")


def test_budget_exhausted_on_first_overflow():
    b = ByteBudget(10)
    assert b.add("aaaa")
    assert not b.add("b" * 20)
    assert b.exhausted


def test_clip_keeps_record_prefix_within_remaining():
    b = ByteBudget(200)
    assert b.add("short")
    huge = "path/to/file.py:1:" + "x" * 10_000
    assert not b.add(huge)
    clipped = b.clip(huge)
    assert clipped.startswith("path/to/file.py:1:")
    assert clipped.endswith(budget_suffix(200))
    # Total joined output stays within the budget.
    assert len("\n".join(["short", clipped]).encode("utf-8")) <= 200


def test_clip_first_record_uses_whole_budget():
    b = ByteBudget(120)
    huge = "y" * 10_000
    assert not b.add(huge)
    clipped = b.clip(huge)
    assert len(clipped.encode("utf-8")) <= 120
    assert clipped.endswith(budget_suffix(120))


# -- take_within_budget -------------------------------------------------------- #


def test_take_passthrough_under_budget():
    b = ByteBudget(1000)
    items = ["one", "two", "three"]
    assert list(take_within_budget(items, b)) == items
    assert not b.exhausted


def test_take_clips_overflowing_record_and_stops():
    b = ByteBudget(150)
    items = ["aaaa", "b" * 500, "never-reached"]
    out = list(take_within_budget(items, b))
    assert out[0] == "aaaa"
    assert len(out) == 2
    assert out[1].startswith("b")
    assert out[1].endswith(budget_suffix(150))
    assert b.exhausted


def test_take_early_termination_does_not_pull_source():
    """The source generator must not be advanced after exhaustion."""
    b = ByteBudget(20)

    def source():
        yield "aaaaaaaa"
        yield "b" * 100
        raise AssertionError("source pulled after budget exhaustion")

    out = list(take_within_budget(source(), b))
    assert len(out) == 2
    assert b.exhausted


# -- ByteBudgetToolset --------------------------------------------------------- #


def _toolset_with(result):
    from pydantic_ai.toolsets import FunctionToolset

    ts = FunctionToolset()

    def emit() -> object:
        return result

    ts.add_function(emit, takes_ctx=False)
    return ByteBudgetToolset(wrapped=ts, max_bytes=200)


async def _call(wrapper, deps=None):
    # Drive call_tool through the real toolset plumbing with a minimal
    # RunContext stand-in.
    from pydantic_ai._run_context import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage

    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
    tools = await wrapper.get_tools(ctx)
    return await wrapper.call_tool("emit", {}, ctx, tools["emit"])


@pytest.mark.anyio
async def test_toolset_truncates_over_ceiling_string():
    wrapper = _toolset_with("z" * 500)
    out = await _call(wrapper)
    assert len(out.encode("utf-8")) <= 200
    assert out.endswith(ceiling_suffix(200))


@pytest.mark.anyio
async def test_toolset_passes_short_string_unchanged():
    wrapper = _toolset_with("short")
    assert await _call(wrapper) == "short"


@pytest.mark.anyio
async def test_toolset_passes_non_string_through():
    wrapper = _toolset_with({"a": 1})
    assert await _call(wrapper) == {"a": 1}


def test_toolset_survives_dataclasses_replace():
    """for_run rebuilds wrappers via dataclasses.replace -- guard the contract."""
    from pydantic_ai.toolsets import FunctionToolset

    a, b = FunctionToolset(), FunctionToolset()
    ts = ByteBudgetToolset(wrapped=a, max_bytes=123)
    replaced = dataclasses.replace(ts, wrapped=b)
    assert replaced.wrapped is b
    assert replaced.max_bytes == 123


# -- Constants ------------------------------------------------------------------ #


def test_ceiling_exceeds_in_tool_budget():
    assert TOOL_RESULT_CEILING_BYTES > DEFAULT_TOOL_RESULT_MAX_BYTES


# -- beartype claw-hook compatibility ------------------------------------------ #


def test_toolset_constructs_under_beartype_hook():
    """`koan run --debug` instruments the whole package via beartype_package.

    beartype resolves WrapperToolset's string annotation `wrapped:
    AbstractToolset[AgentDepsT]` against THIS module's namespace (the
    dataclass-generated __init__ lives here), so AbstractToolset must be
    importable from koan.tools.byte_budget. pytest runs without the claw
    hook, so this must run in a subprocess with the hook active -- a plain
    in-process test passes even when the app is broken (observed 2026-07-14:
    every ByteBudgetToolset(...) call raised
    BeartypeCallHintForwardRefException in the app while the suite was green).
    """
    import subprocess
    import sys

    code = (
        "from beartype.claw import beartype_package\n"
        "beartype_package('koan')\n"
        "from koan.tools.builtin_tools import build_builtin_toolset\n"
        "from koan.tools.byte_budget import ByteBudgetToolset\n"
        "ByteBudgetToolset(wrapped=build_builtin_toolset())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"beartype-hooked construction failed:\n{proc.stderr}"

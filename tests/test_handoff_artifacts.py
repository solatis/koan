# Unit tests for koan.tools.handoff_artifacts.
#
# Tests the handover-injection module: envelope formatting, immutable
# handover selection, read-on-demand listing, and the full pre-seed
# drain/inject/mark cycle including dedup and error handling.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from koan.phases import PhaseContext
from koan.state import AgentState, AppState
from koan.tools.handoff_artifacts import (
    apply_artifact_cache_point,
    build_handover_listing,
    format_handoff_message,
    living_artifacts,
    preseed_pending_artifacts,
    preseed_pending_listing,
    reset_phase_context,
    select_immutable_handovers,
    subagent_candidates,
)


# -- format_handoff_message -------------------------------------------------- #


def test_format_handoff_message_envelope():
    """format_handoff_message wraps content in a <handoff_artifact name=...> envelope."""
    msg = format_handoff_message("brief.md", "# Brief\nContent here.")
    assert '<handoff_artifact name="brief.md">' in msg
    assert "# Brief\nContent here." in msg
    assert "</handoff_artifact>" in msg
    assert 'error="true"' not in msg


def test_format_handoff_message_error_attribute():
    """format_handoff_message adds error=\"true\" when error=True."""
    msg = format_handoff_message("brief.md", "(error reading)", error=True)
    assert 'error="true"' in msg
    assert '<handoff_artifact name="brief.md"' in msg
    assert "(error reading)" in msg


# -- select_immutable_handovers ---------------------------------------------- #


def test_select_immutable_keeps_immutable():
    """select_immutable_handovers returns immutable artifact names."""
    result = select_immutable_handovers(
        ("brief.md", "core-flows.md", "tech-plan.md"),
        injected=set(),
    )
    assert result == ["brief.md", "core-flows.md", "tech-plan.md"]


def test_select_immutable_drops_living_documents():
    """select_immutable_handovers drops living-document families (plan, milestones)."""
    result = select_immutable_handovers(
        ("brief.md", "milestones.md", "plan-milestone-1.md"),
        injected=set(),
    )
    assert result == ["brief.md"]
    assert "milestones.md" not in result
    assert "plan-milestone-1.md" not in result


def test_select_immutable_drops_already_injected():
    """select_immutable_handovers skips names already in injected."""
    result = select_immutable_handovers(
        ("brief.md", "core-flows.md"),
        injected={"brief.md"},
    )
    assert result == ["core-flows.md"]
    assert "brief.md" not in result


def test_select_immutable_preserves_order():
    """select_immutable_handovers preserves the input order of required."""
    result = select_immutable_handovers(
        ("tech-plan.md", "brief.md", "core-flows.md"),
        injected=set(),
    )
    assert result == ["tech-plan.md", "brief.md", "core-flows.md"]


def test_select_immutable_skips_unparseable_names():
    """select_immutable_handovers silently skips names that fail parse_artifact_filename."""
    result = select_immutable_handovers(
        ("brief.md", "not-an-artifact.txt", "README.md"),
        injected=set(),
    )
    assert result == ["brief.md"]


def test_select_immutable_empty_required():
    """select_immutable_handovers returns [] for an empty required tuple."""
    assert select_immutable_handovers((), injected=set()) == []


# -- build_handover_listing -------------------------------------------------- #


def test_build_handover_listing_lists_artifacts(tmp_path):
    """build_handover_listing lists artifact files not in exclude."""
    (tmp_path / "brief.md").write_text("# Brief")
    (tmp_path / "milestones.md").write_text("# Milestones")
    result = build_handover_listing(str(tmp_path), exclude=set())
    assert "brief.md" in result
    assert "milestones.md" in result
    assert "## Artifacts available to read on demand" in result


def test_build_handover_listing_excludes_injected(tmp_path):
    """build_handover_listing omits filenames in the exclude set."""
    (tmp_path / "brief.md").write_text("# Brief")
    (tmp_path / "milestones.md").write_text("# Milestones")
    result = build_handover_listing(str(tmp_path), exclude={"brief.md"})
    assert "brief.md" not in result
    assert "milestones.md" in result


def test_build_handover_listing_empty_when_all_excluded(tmp_path):
    """build_handover_listing returns \"\" when every artifact is excluded."""
    (tmp_path / "brief.md").write_text("# Brief")
    result = build_handover_listing(str(tmp_path), exclude={"brief.md"})
    assert result == ""


def test_build_handover_listing_ignores_non_artifact_files(tmp_path):
    """build_handover_listing omits files that are not valid artifact names."""
    (tmp_path / "brief.md").write_text("# Brief")
    (tmp_path / "README.md").write_text("# Readme")
    (tmp_path / "notes.txt").write_text("notes")
    result = build_handover_listing(str(tmp_path), exclude=set())
    assert "brief.md" in result
    assert "README.md" not in result
    assert "notes.txt" not in result


def test_build_handover_listing_empty_run_dir():
    """build_handover_listing returns \"\" when run_dir is empty."""
    assert build_handover_listing("", exclude=set()) == ""


def test_build_handover_listing_unreadable_dir(tmp_path):
    """build_handover_listing returns \"\" when run_dir cannot be listed."""
    # Use a path that does not exist.
    result = build_handover_listing(str(tmp_path / "nonexistent"), exclude=set())
    assert result == ""


# -- preseed_pending_artifacts ----------------------------------------------- #


def _make_agent(run_dir: str = "") -> AgentState:
    """Build a minimal AgentState for preseed tests."""
    return AgentState(
        agent_id="test-agent",
        role="orchestrator",
        subagent_dir="",
        run_dir=run_dir,
    )


def _make_app_state(run_dir: str = "") -> AppState:
    """Build a minimal AppState with the given run_dir."""
    app = AppState()
    app.run.run_dir = run_dir or None
    return app


def test_preseed_injects_existing_pending_files(tmp_path):
    """preseed_pending_artifacts appends one <handoff_artifact> message per pending file."""
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief content")

    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md"]
    app = _make_app_state()

    preseed_pending_artifacts(agent, app)

    assert len(agent.message_history) == 1
    from pydantic_ai.messages import ModelRequest
    msg = agent.message_history[0]
    assert isinstance(msg, ModelRequest)
    content = msg.parts[0].content
    assert '<handoff_artifact name="brief.md">' in content
    assert "# Brief content" in content
    assert "brief.md" in agent.injected_artifacts
    assert agent.pending_artifacts == []


def test_preseed_deduplication(tmp_path):
    """preseed_pending_artifacts is a no-op for artifacts already in injected_artifacts."""
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief")

    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md"]
    agent.injected_artifacts = {"brief.md"}  # already injected
    app = _make_app_state()

    preseed_pending_artifacts(agent, app)

    assert agent.message_history == []
    # Still only one entry in injected (not double-added).
    assert agent.injected_artifacts == {"brief.md"}


def test_preseed_absent_file_skipped_and_not_marked(tmp_path):
    """preseed_pending_artifacts skips absent files and does not mark them injected."""
    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md"]  # file does not exist
    app = _make_app_state()

    preseed_pending_artifacts(agent, app)

    assert agent.message_history == []
    assert "brief.md" not in agent.injected_artifacts


def test_preseed_second_call_is_noop(tmp_path):
    """A second preseed call is a no-op (pending already drained on first call)."""
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief")

    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md"]
    app = _make_app_state()

    preseed_pending_artifacts(agent, app)
    preseed_pending_artifacts(agent, app)  # second call with empty pending

    assert len(agent.message_history) == 1


def test_preseed_uses_app_state_run_dir_fallback(tmp_path):
    """preseed_pending_artifacts falls back to app_state.run.run_dir when agent.run_dir is empty."""
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief via app_state")

    agent = _make_agent(run_dir="")  # no run_dir on agent
    agent.pending_artifacts = ["brief.md"]
    app = _make_app_state(run_dir=str(tmp_path))

    preseed_pending_artifacts(agent, app)

    assert len(agent.message_history) == 1
    assert "# Brief via app_state" in agent.message_history[0].parts[0].content


def test_preseed_error_on_ioerror(tmp_path):
    """preseed_pending_artifacts injects an error placeholder on non-FileNotFoundError OSError."""
    import stat

    brief = tmp_path / "brief.md"
    brief.write_text("# Secret")
    # Remove read permission to cause an PermissionError (a subclass of OSError).
    brief.chmod(0)

    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md"]
    app = _make_app_state()

    try:
        preseed_pending_artifacts(agent, app)
    finally:
        brief.chmod(stat.S_IRUSR | stat.S_IWUSR)  # restore so tmp_path cleanup works

    # An error placeholder should have been injected.
    assert len(agent.message_history) == 1
    content = agent.message_history[0].parts[0].content
    assert 'error="true"' in content
    assert "brief.md" in agent.injected_artifacts


def test_preseed_multiple_pending_all_injected(tmp_path):
    """preseed_pending_artifacts injects all pending files in order."""
    (tmp_path / "brief.md").write_text("# Brief")
    (tmp_path / "core-flows.md").write_text("# Core flows")

    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md", "core-flows.md"]
    app = _make_app_state()

    preseed_pending_artifacts(agent, app)

    assert len(agent.message_history) == 2
    names = {msg.parts[0].content.split('"')[1] for msg in agent.message_history}
    assert names == {"brief.md", "core-flows.md"}
    assert "brief.md" in agent.injected_artifacts
    assert "core-flows.md" in agent.injected_artifacts


# -- living_artifacts -------------------------------------------------------- #


def test_living_artifacts_returns_living_family_members():
    """living_artifacts returns only names whose family is in LIVING_DOC_FAMILIES."""
    result = living_artifacts(["brief.md", "milestones.md", "plan-milestone-1.md"])
    assert "milestones.md" in result
    assert "plan-milestone-1.md" in result
    assert "brief.md" not in result


def test_living_artifacts_drops_immutable_families():
    """living_artifacts drops immutable artifacts (brief, core-flows, tech-plan)."""
    result = living_artifacts(["brief.md", "core-flows.md", "tech-plan.md"])
    assert result == []


def test_living_artifacts_skips_unparseable_names():
    """living_artifacts silently skips names that fail parse_artifact_filename."""
    result = living_artifacts(["milestones.md", "README.md", "notes.txt"])
    assert result == ["milestones.md"]
    assert "README.md" not in result
    assert "notes.txt" not in result


def test_living_artifacts_empty_input():
    """living_artifacts returns [] for an empty input list."""
    assert living_artifacts([]) == []


def test_living_artifacts_preserves_order():
    """living_artifacts preserves the order of input names."""
    result = living_artifacts(["plan-milestone-2.md", "milestones.md"])
    assert result == ["plan-milestone-2.md", "milestones.md"]


# -- subagent_candidates ----------------------------------------------------- #


def _ctx_for_executor(artifacts: list[str]) -> PhaseContext:
    """Build a PhaseContext as populated for an executor subagent."""
    return PhaseContext(run_dir="", subagent_dir="", executor_artifacts=artifacts)


def _ctx_for_reviewer(prompt: str, target: str) -> PhaseContext:
    """Build a PhaseContext as populated for a reviewer subagent."""
    return PhaseContext(run_dir="", subagent_dir="", reviewer_prompt=prompt, reviewer_target=target)


def test_subagent_candidates_executor_returns_all_artifacts():
    """subagent_candidates returns tuple(executor_artifacts) for an executor context."""
    ctx = _ctx_for_executor(["brief.md", "tech-plan.md", "plan-milestone-3.md"])
    result = subagent_candidates(ctx)
    assert result == ("brief.md", "tech-plan.md", "plan-milestone-3.md")


def test_subagent_candidates_tech_plan_reviewer_includes_core_flows():
    """TECH_PLAN_REVIEWER gets brief.md + core-flows.md as candidates."""
    ctx = _ctx_for_reviewer("TECH_PLAN_REVIEWER", "tech-plan.md")
    result = subagent_candidates(ctx)
    assert result == ("brief.md", "core-flows.md")
    # Target is excluded -- it is always read explicitly
    assert "tech-plan.md" not in result


def test_subagent_candidates_plan_reviewer_includes_tech_plan_and_milestones():
    """PLAN_REVIEWER gets brief.md + tech-plan.md + milestones.md as candidates."""
    ctx = _ctx_for_reviewer("PLAN_REVIEWER", "plan-milestone-3.md")
    result = subagent_candidates(ctx)
    assert result == ("brief.md", "tech-plan.md", "milestones.md")
    # Target is excluded
    assert "plan-milestone-3.md" not in result


def test_subagent_candidates_milestone_reviewer_includes_tech_plan():
    """MILESTONE_REVIEWER gets brief.md + tech-plan.md as candidates."""
    ctx = _ctx_for_reviewer("MILESTONE_REVIEWER", "milestones.md")
    result = subagent_candidates(ctx)
    assert result == ("brief.md", "tech-plan.md")
    assert "milestones.md" not in result


def test_subagent_candidates_generic_reviewer_gets_brief_only():
    """A reviewer with an unknown prompt tag gets only brief.md as a candidate."""
    ctx = _ctx_for_reviewer("UNKNOWN_REVIEWER", "some-artifact.md")
    result = subagent_candidates(ctx)
    assert result == ("brief.md",)


def test_subagent_candidates_reviewer_target_only_no_prompt():
    """A reviewer context with target but no prompt still gets brief.md."""
    ctx = PhaseContext(run_dir="", subagent_dir="", reviewer_target="tech-plan.md")
    result = subagent_candidates(ctx)
    assert "brief.md" in result
    # Target itself is excluded
    assert "tech-plan.md" not in result


def test_subagent_candidates_empty_context_returns_empty():
    """An empty PhaseContext (scout-like) returns an empty tuple."""
    ctx = PhaseContext(run_dir="", subagent_dir="")
    assert subagent_candidates(ctx) == ()


def test_subagent_candidates_immutable_filter_drops_living_from_reviewer():
    """select_immutable_handovers applied to PLAN_REVIEWER candidates drops milestones.md."""
    ctx = _ctx_for_reviewer("PLAN_REVIEWER", "plan-milestone-3.md")
    candidates = subagent_candidates(ctx)
    pending = select_immutable_handovers(candidates, injected=set())
    # milestones.md is living and must not be injected
    assert "milestones.md" not in pending
    # brief.md and tech-plan.md are immutable and must be selected
    assert "brief.md" in pending
    assert "tech-plan.md" in pending


# -- reset_phase_context ----------------------------------------------------- #


def test_reset_phase_context_clears_everything(tmp_path):
    """reset_phase_context clears all six conversation and dedup fields."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    agent = _make_agent(run_dir=str(tmp_path))
    # Populate all fields that should be cleared.
    agent.message_history = [ModelRequest(parts=[UserPromptPart(content="prior turn")])]
    agent.injected_artifacts = {"brief.md"}
    agent.injected_context_files = {"/x/AGENTS.md"}
    agent.pending_context_files = ["/x/y"]
    agent.pending_artifacts = ["z.md"]
    agent.pending_listing = "## Artifacts available..."

    reset_phase_context(agent)

    assert agent.message_history == []
    assert agent.injected_artifacts == set()
    assert agent.injected_context_files == set()
    assert agent.pending_context_files == []
    assert agent.pending_artifacts == []
    assert agent.pending_listing is None


def test_reset_phase_context_is_noop_on_empty_agent():
    """reset_phase_context on a fresh AgentState changes nothing (bootstrap no-op)."""
    agent = _make_agent()
    reset_phase_context(agent)
    assert agent.message_history == []
    assert agent.injected_artifacts == set()
    assert agent.pending_listing is None


# -- preseed_pending_listing ------------------------------------------------- #


def test_preseed_pending_listing_appends_message():
    """preseed_pending_listing drains pending_listing and appends it as its own ModelRequest."""
    from pydantic_ai.messages import ModelRequest

    agent = _make_agent()
    agent.pending_listing = "## Artifacts available to read on demand\n\n- `plan.md`\n"

    preseed_pending_listing(agent)

    assert len(agent.message_history) == 1
    msg = agent.message_history[0]
    assert isinstance(msg, ModelRequest)
    assert "## Artifacts available to read on demand" in msg.parts[0].content
    assert agent.pending_listing is None


def test_preseed_pending_listing_noop_when_empty():
    """preseed_pending_listing is a no-op when pending_listing is None or empty string."""
    agent = _make_agent()
    agent.pending_listing = None
    preseed_pending_listing(agent)
    assert agent.message_history == []

    agent.pending_listing = ""
    preseed_pending_listing(agent)
    assert agent.message_history == []


def test_preseed_order_artifacts_before_listing(tmp_path):
    """Artifact message lands at index 0, listing message at index 1."""
    (tmp_path / "brief.md").write_text("# Brief")
    app = _make_app_state()
    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md"]
    agent.pending_listing = "LISTING"

    preseed_pending_artifacts(agent, app)
    preseed_pending_listing(agent)

    assert len(agent.message_history) == 2
    assert '<handoff_artifact name="brief.md">' in agent.message_history[0].parts[0].content
    assert "LISTING" in agent.message_history[1].parts[0].content


def test_preseed_multi_artifact_order_stable(tmp_path):
    """Three artifacts land in message_history in brief -> core-flows -> tech-plan order."""
    (tmp_path / "brief.md").write_text("# Brief")
    (tmp_path / "core-flows.md").write_text("# Core flows")
    (tmp_path / "tech-plan.md").write_text("# Tech plan")
    app = _make_app_state()
    agent = _make_agent(run_dir=str(tmp_path))
    agent.pending_artifacts = ["brief.md", "core-flows.md", "tech-plan.md"]

    preseed_pending_artifacts(agent, app)

    assert len(agent.message_history) == 3
    assert 'name="brief.md"' in agent.message_history[0].parts[0].content
    assert 'name="core-flows.md"' in agent.message_history[1].parts[0].content
    assert 'name="tech-plan.md"' in agent.message_history[2].parts[0].content


# -- apply_artifact_cache_point ----------------------------------------------- #


def _make_agent_with_provider(role: str = "orchestrator", provider: str = "anthropic") -> AgentState:
    """Build an AgentState with an explicit role and provider for CachePoint tests."""
    agent = AgentState(agent_id="test-agent", role=role, subagent_dir="", run_dir="")
    agent.provider = provider
    return agent


def _artifact_msg(text: str = "ARTIFACT_TEXT"):
    """Build a ModelRequest with a plain-str UserPromptPart (preseed shape)."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    return ModelRequest(parts=[UserPromptPart(content=text)])


def test_apply_cache_point_long_tier_attaches_cache_point():
    """Long-tier role + anthropic provider: content becomes [str, CachePoint(ttl='1h')]."""
    from pydantic_ai.messages import CachePoint

    agent = _make_agent_with_provider(role="orchestrator", provider="anthropic")
    agent.message_history.append(_artifact_msg("ARTIFACT"))

    apply_artifact_cache_point(agent, 0)

    part = agent.message_history[0].parts[-1]
    assert isinstance(part.content, list)
    assert part.content[0] == "ARTIFACT"
    assert isinstance(part.content[1], CachePoint)
    assert part.content[1].ttl == "1h"


def test_apply_cache_point_short_tier_no_op():
    """Short-tier role (scout): no CachePoint attached; content stays a plain str."""
    agent = _make_agent_with_provider(role="scout", provider="anthropic")
    agent.message_history.append(_artifact_msg("ARTIFACT"))

    apply_artifact_cache_point(agent, 0)

    assert agent.message_history[0].parts[-1].content == "ARTIFACT"


def test_apply_cache_point_sentinel_index_no_op():
    """Sentinel target_index=-1: no error, no change to history (turn-2+ no-op)."""
    agent = _make_agent_with_provider(role="orchestrator", provider="anthropic")
    agent.message_history.append(_artifact_msg("ARTIFACT"))

    apply_artifact_cache_point(agent, -1)

    assert agent.message_history[0].parts[-1].content == "ARTIFACT"


def test_apply_cache_point_turn2_regression_tail_not_mutated():
    """Turn-2+ regression (reviewer C1): sentinel -1 does NOT attach to the churny tail.

    History has an artifact message at index 0 and a churny tail message at
    index 1.  Calling with -1 (nothing preseeded this turn) must leave the
    tail message untouched -- it must NOT get a long-TTL CachePoint.
    """
    agent = _make_agent_with_provider(role="orchestrator", provider="anthropic")
    agent.message_history.append(_artifact_msg("ARTIFACT"))
    agent.message_history.append(_artifact_msg("CHURNY_TAIL"))

    apply_artifact_cache_point(agent, -1)

    # Tail message must stay a plain str -- no CachePoint leaked onto it.
    assert agent.message_history[1].parts[-1].content == "CHURNY_TAIL"
    # Artifact message also untouched (sentinel means nothing was preseeded).
    assert agent.message_history[0].parts[-1].content == "ARTIFACT"


def test_apply_cache_point_idempotent():
    """Calling twice with the same valid target_index attaches only one CachePoint."""
    from pydantic_ai.messages import CachePoint

    agent = _make_agent_with_provider(role="orchestrator", provider="anthropic")
    agent.message_history.append(_artifact_msg("ARTIFACT"))

    apply_artifact_cache_point(agent, 0)
    apply_artifact_cache_point(agent, 0)

    content = agent.message_history[0].parts[-1].content
    assert isinstance(content, list)
    cache_points = [p for p in content if isinstance(p, CachePoint)]
    assert len(cache_points) == 1


def test_apply_cache_point_no_cache_provider_no_op():
    """Provider with no koan-managed cache (google): no CachePoint even for long-tier role."""
    agent = _make_agent_with_provider(role="orchestrator", provider="google")
    agent.message_history.append(_artifact_msg("ARTIFACT"))

    apply_artifact_cache_point(agent, 0)

    assert agent.message_history[0].parts[-1].content == "ARTIFACT"


def test_apply_cache_point_persistence_rides_forward():
    """After attaching, the CachePoint persists on the original artifact message object.

    Simulates all_messages() growth: the artifact ModelRequest is wrapped in a
    larger list with later messages.  The CachePoint must still be present on
    the artifact message at its original position (rides-forward invariant).
    """
    from pydantic_ai.messages import CachePoint, ModelRequest, UserPromptPart

    agent = _make_agent_with_provider(role="orchestrator", provider="anthropic")
    agent.message_history.append(_artifact_msg("ARTIFACT"))

    apply_artifact_cache_point(agent, 0)

    # Simulate later turns appending churny messages after the artifact message.
    artifact_msg = agent.message_history[0]
    simulated_all_messages = [
        artifact_msg,
        ModelRequest(parts=[UserPromptPart(content="LATER_TURN_1")]),
        ModelRequest(parts=[UserPromptPart(content="LATER_TURN_2")]),
    ]

    # The artifact message (index 0) still carries the CachePoint.
    content = simulated_all_messages[0].parts[-1].content
    assert isinstance(content, list)
    assert isinstance(content[1], CachePoint)
    assert content[1].ttl == "1h"

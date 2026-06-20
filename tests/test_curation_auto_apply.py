# Negative-presence guards for the M7 curation auto-apply removal.
#
# Each test asserts that a symbol deleted in M7 is truly gone. These are
# removal guards: if any deleted symbol is re-introduced, the test fails
# immediately rather than silently drifting. The pattern mirrors the
# vocabulary drift guard in test_vocabulary_drift.py.

from __future__ import annotations


def test_propose_memory_core_not_importable() -> None:
    """propose_memory_core must not exist in koan.tools.koan_tools (removed in M7).

    The function implemented the koan_memory_propose approval gate. Its absence
    confirms the interactive curation path is fully retired.
    """
    import koan.tools.koan_tools as mod
    assert not hasattr(mod, "propose_memory_core"), (
        "propose_memory_core still present in koan.tools.koan_tools -- remove it (M7)"
    )


def test_yolo_memory_propose_response_not_importable() -> None:
    """_yolo_memory_propose_response must not exist in koan.tools.koan_tools (removed in M7).

    This helper synthesised an all-approved curation payload for yolo mode.
    Its absence confirms the yolo path for propose/approve is also retired.
    """
    import koan.tools.koan_tools as mod
    assert not hasattr(mod, "_yolo_memory_propose_response"), (
        "_yolo_memory_propose_response still present in koan.tools.koan_tools -- remove it (M7)"
    )


def test_koan_memory_propose_not_in_toolset() -> None:
    """koan_memory_propose must not appear in the full vocabulary of build_koan_toolset (removed in M7).

    Confirms the tool is neither registered nor reachable by the orchestrator.
    The full vocabulary (allowed_names=None) is used so no filter hides a stray
    registration.
    """
    from koan.tools.koan_tools import build_koan_toolset
    ts = build_koan_toolset()
    # ts.tools is a dict keyed by tool name.
    names = set(ts.tools.keys())
    assert "koan_memory_propose" not in names, (
        "koan_memory_propose still registered in build_koan_toolset -- remove it (M7)"
    )


def test_render_curation_payload_not_importable() -> None:
    """_render_curation_payload must not exist in koan.web.uploads (removed in M7).

    This function rendered per-decision attachment blocks for the curation
    payload delivered to the orchestrator. Its absence confirms the delivery
    path is retired alongside the approval gate.
    """
    import koan.web.uploads as mod
    assert not hasattr(mod, "_render_curation_payload"), (
        "_render_curation_payload still present in koan.web.uploads -- remove it (M7)"
    )


def test_active_curation_batch_not_in_run_model() -> None:
    """active_curation_batch must not be a field on the Run projection model (removed in M7).

    Removing this field from Run also removes it from the wire shape; any
    frontend consumer of run.activeCurationBatch would crash on a stale bundle.
    """
    from koan.projections import Run
    assert "active_curation_batch" not in Run.model_fields, (
        "active_curation_batch still in Run.model_fields -- remove it (M7)"
    )


def test_proposal_not_importable_from_projections() -> None:
    """Proposal must not be importable from koan.projections (removed in M7).

    Proposal was the per-entry wire type for koan_memory_propose. Its absence
    ensures no non-eval test can import it and crash pytest collection.
    """
    import koan.projections as mod
    assert not hasattr(mod, "Proposal"), (
        "Proposal still present in koan.projections -- remove it (M7)"
    )


def test_active_curation_batch_not_importable_from_projections() -> None:
    """ActiveCurationBatch must not be importable from koan.projections (removed in M7).

    ActiveCurationBatch was the batch-level wire type for koan_memory_propose.
    Its absence confirms the propose plumbing is fully removed from the projection.
    """
    import koan.projections as mod
    assert not hasattr(mod, "ActiveCurationBatch"), (
        "ActiveCurationBatch still present in koan.projections -- remove it (M7)"
    )


def test_memory_propose_future_not_in_interactions_state() -> None:
    """memory_propose_future must not be a field on the interactions dataclass (removed in M7).

    This asyncio future was the blocking mechanism for koan_memory_propose.
    Its absence confirms the interactive curation path cannot be re-entered.
    """
    import dataclasses
    from koan.state import InteractionState
    field_names = {f.name for f in dataclasses.fields(InteractionState)}
    assert "memory_propose_future" not in field_names, (
        "memory_propose_future still in Interactions dataclass -- remove it (M7)"
    )


def test_curation_step2_guidance_has_no_memory_propose_reference() -> None:
    """The curation phase step-2 guidance string must not reference koan_memory_propose (removed in M7).

    Guards the prose rewrite in koan/phases/curation.py: if koan_memory_propose
    is mentioned anywhere in step-2 guidance the orchestrator might attempt to
    call a tool that no longer exists.
    """
    from koan.phases import PhaseContext
    from koan.phases.curation import step_guidance

    ctx = PhaseContext(run_dir="/tmp", subagent_dir="/tmp")
    guidance = step_guidance(2, ctx)
    full_text = "\n".join(guidance.instructions)
    assert "koan_memory_propose" not in full_text, (
        "koan_memory_propose still referenced in curation step-2 guidance -- remove it (M7)"
    )

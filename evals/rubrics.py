# evals/rubrics.py
# Rubric criteria as code data. Each criterion is a single string judged
# by a BinaryJudgementNode against LLMTestCaseParams.ACTUAL_OUTPUT.
#
# FIXTURE_RUBRICS:       fixture-wide criteria (apply to all tasks in fixture)
# TASK_RUBRIC_ADDENDUMS: task-specific additional criteria, concatenated after fixture
# CROSS_PHASE_RUBRICS:   cross-phase rubric body for holistic judgment per case
#
# Criterion strings are byte-equal to the original bullet text minus the
# "- " or "* " prefix and trailing whitespace. Cross-phase bodies are lifted
# verbatim from the case file body (after lstrip("\n")).

from __future__ import annotations


# -- Fixture-level rubrics -----------------------------------------------------
# Key: (fixture_id, phase, section) -- phase uses canonical koan form (dash-sep).

FIXTURE_RUBRICS: dict[tuple[str, str, str], list[str]] = {
    ("koan-1", "intake", "summary"): [
        "The task scope: a concise statement of what is being built or changed and which user-facing or internal surfaces are affected.",
        "Findings relevant for planning: specific existing code patterns, constraints, or integration points the planner will need.",
        "Decisions made during intake: explicit answers to ambiguities that surfaced in the questions phase.",
        "Newly discovered context and rationale: facts about the codebase or the problem that were not obvious from the task description.",
        "Architecture or component points: the files or modules the implementation will likely touch, named specifically.",
    ],
    ("koan-1", "intake", "questions"): [
        "The orchestrator raised at least one question that flags a contradiction, inaccuracy, or mistake in the task description by cross-referencing the claim against the actual codebase.",
        "The orchestrator raised at least one question that probes the expected behavior of an API or system surface the task touches, when the task description does not specify.",
        "The orchestrator raised at least one question that seeks the broader use case or intent behind the requested change to ground scope decisions.",
        "The orchestrator raised at least one question that resolves ambiguity about downstream effects the task description is silent on (e.g. side effects on UI, events, persistence).",
    ],
    ("koan-1", "intake", "artifacts"): [
        "No files were created or modified during the intake phase (the created and modified artifact sets are both empty).",
    ],
    ("koan-1", "intake", "overall"): [
        "Scout discipline: the orchestrator launched scouts only when the task genuinely required broad codebase investigation; for a trivial self-contained change, no scouts were spawned.",
        "Memory usage: the orchestrator called at least one of `koan_reflect` or `koan_search` during intake.",
        "Codebase grounding: the orchestrator opened the files the task description references and verified claims against what it read, rather than taking the task description at face value.",
    ],
    ("koan-1", "plan-spec", "summary"): [
        "Approach: a clear description of the overall strategy for the implementation.",
        "Key decisions: the architectural or design choices made, each with a one-line rationale.",
        "Files to touch: specific file paths from the actual codebase that will be modified, not generic module names.",
        "Ordering: the sequence in which changes will be applied, with any dependencies between steps called out.",
    ],
    ("koan-1", "plan-spec", "questions"): [
        "The orchestrator asked no questions during plan-spec, or asked only targeted clarifications that were strictly necessary to resolve a concrete implementation ambiguity not resolvable by reading the codebase.",
    ],
    ("koan-1", "plan-spec", "artifacts"): [
        "plan.md is present in the all_present artifact set for the plan-spec phase.",
        "plan.md cites at least 3 specific file paths from the actual codebase (not invented or generic paths).",
    ],
    ("koan-1", "plan-spec", "overall"): [
        "No invented paths: every file path cited in plan.md plausibly exists in the koan codebase (paths like `koan/web/mcp_endpoint.py`, `koan/state.py`, `koan/driver.py` are real; invented module names are a red flag).",
        "References real function or module names: the plan cites at least a few specific function names, class names, or variable names that actually appear in the codebase.",
        "Internally consistent: the approach described in the plan does not contradict itself across sections.",
        "Scoped appropriately: the plan addresses only what the task asked for and does not propose unrelated refactors or scope creep.",
    ],
}


# -- Task-specific addendum rubrics --------------------------------------------
# Key: (fixture_id, task_id, phase, section).
# Concatenated after the fixture-level criteria at grade time.

TASK_RUBRIC_ADDENDUMS: dict[tuple[str, str, str, str], list[str]] = {
    # add-logs / intake
    ("koan-1", "add-logs", "intake", "summary"): [
        "Identified the logging imbalance: the memory subsystem (`koan/memory/`) accounts for roughly half of all logging calls, while the phase modules (`koan/phases/*.py`) have zero logging, and the rest of the system (driver, subagent, web server) has sparse coverage.",
        "Identified the existing logging infrastructure: centralized setup in `koan/logger.py` with `get_logger()`, dual handlers (console + file to `{run_dir}/koan.log`), plain-text format with timestamp/name/level/message.",
        "Documented which subsystems need logging and why -- at minimum the phase modules, but ideally also the driver's phase-transition path, subagent lifecycle, and permission checks.",
        "Made a decision about frontend scope (in or out) based on user clarification, and stated that decision explicitly.",
        "Noted that the existing logging is unstructured (format strings, no JSON or structured fields) and stated whether that pattern should be continued or changed.",
        "Identified that the goal is after-the-fact debuggability -- being able to reconstruct what happened during a run from log output alone, which is critical for LLM-driven workflows where failures are non-deterministic.",
    ],
    ("koan-1", "add-logs", "intake", "questions"): [
        'Asked whether frontend logging is in scope or only backend (the project has both a Python backend and a TypeScript/React frontend -- the task says "application" without specifying which side).',
        "Identified the logging gap between the memory subsystem (heavily logged) and the rest of the system (sparsely logged), and asked whether the goal is to bring the rest up to the memory subsystem's level of coverage.",
        "Asked what the logs are meant to help with: after-the-fact debugging of failed runs, live observability, or both.",
        "Asked about the current inability to trace what went wrong after a run fails -- i.e., whether the goal is evidence-driven debugging (reconstructing LLM decisions, phase transitions, tool call outcomes from log output).",
        "Asked whether there is a preferred logging pattern or framework to follow, or whether the existing `get_logger()` / `koan.logger` pattern should be extended to uncovered modules.",
        'Asked about log level strategy: what events warrant info vs debug vs warning, or whether everything should default to debug given the task description says "debug logs."',
    ],
    ("koan-1", "add-logs", "intake", "overall"): [
        "Performed a broad survey of logging coverage across the codebase rather than fixating on a single module -- at minimum, the orchestrator examined files in `koan/phases/`, `koan/driver.py`, `koan/subagent.py`, and `koan/memory/` to understand the current distribution.",
        "Recognized the frontend/backend ambiguity and surfaced it as a question rather than silently assuming one scope.",
        "Did not prematurely narrow scope to a single subsystem before understanding the full picture.",
    ],
    # add-logs / plan-spec
    ("koan-1", "add-logs", "plan-spec", "summary"): [
        "Which subsystems will receive new logging and in what priority order -- at minimum the phase modules (`koan/phases/*.py`) should be listed, since they currently have zero logging despite being the core orchestration layer.",
        'Specific file paths for each subsystem targeted (not "add logging to phases" but naming actual files like `koan/phases/intake.py`, `koan/phases/plan_spec.py`, `koan/driver.py`, etc.).',
        "What events to log within each subsystem -- for phases: step transitions, guidance delivery, phase boundaries; for the driver: orchestrator spawn, phase commits, run completion; for subagents: spawn, registration, exit.",
        "Whether to extend the existing `get_logger()` pattern from `koan/logger.py` to all new logging sites, maintaining the `koan.<scope>` namespace convention.",
        "Log level assignment strategy: what constitutes debug (verbose tracing) vs info (operational milestones) vs warning (recoverable issues) for this codebase.",
        "Frontend logging plan if frontend was determined to be in scope during intake -- what to log in the TypeScript/React layer and through what mechanism.",
    ],
    ("koan-1", "add-logs", "plan-spec", "overall"): [
        "Cover multiple subsystems -- a plan that only adds logging to one module (e.g., only the driver, or only phases) fails to reflect the broad survey expected from intake.",
        "Preserve the existing logging infrastructure by extending `koan/logger.py` and `get_logger()`, not introducing a competing framework or reinventing the handler setup.",
        "Not propose removing or restructuring existing logging in the memory subsystem (the memory subsystem is already well-logged; the plan should bring other modules up to a comparable level, not tear down what exists).",
        "Stay scoped to adding logs without proposing broader refactors (e.g., restructuring phase modules, changing the driver loop, adding observability infrastructure) unless directly required for logging.",
    ],
    # scout-concurrency-settings-only / intake
    ("koan-1", "scout-concurrency-settings-only", "intake", "summary"): [
        "The specific frontend surfaces that currently expose scout concurrency: `frontend/src/components/organisms/NewRunForm.tsx` (the per-run field being removed) and the Settings UI (`SettingsOverlay.tsx` / `SettingsPage.tsx`) where it continues to live.",
        "The settings store key that persists the default value (`defaultScoutConcurrency` on the Zustand settings slice) and the fact that the new-run flow should read from it after the per-run field is removed.",
        "The chosen fate of the `scoutConcurrency` parameter in the `api.startRun` signature (dropped, kept-optional, or kept-required) and the reasoning.",
        "The chosen fate of the `scout_concurrency` field in the `/api/start-run` request body, and how the backend (`koan/config.py`, start-run handler) continues to obtain the value.",
        "Whether any UI copy around scout concurrency in Settings needs updating (e.g. to clarify that this is now the only place it's configured).",
    ],
    ("koan-1", "scout-concurrency-settings-only", "intake", "questions"): [
        "Asked what the new-run flow should use as the scout-concurrency value once the input is gone (settings store default vs. a hardcoded constant vs. reading from the backend config).",
        "Asked whether the `scoutConcurrency` parameter in the `api.startRun` signature should be dropped, kept optional, or kept required for backward compatibility with callers.",
        "Asked whether the `/api/start-run` request body should still include `scout_concurrency` at all, or whether the backend should derive it entirely from server-side config.",
        "Asked whether the existing Settings UI needs copy or layout updates now that it's the sole home for this control.",
        "Asked whether per-run overrides should remain possible via some other mechanism (e.g. a dev-only URL param, a CLI flag) or whether they are being fully eliminated.",
    ],
    # scout-concurrency-settings-only / plan-spec
    ("koan-1", "scout-concurrency-settings-only", "plan-spec", "summary"): [
        "The specific files that will change, named explicitly: at minimum `frontend/src/components/organisms/NewRunForm.tsx` (field + state removed) and `frontend/src/api/client.ts` (the `scoutConcurrency` parameter handling in `startRun`), plus any upstream caller in `App.tsx` that stops piping the value through.",
        "The mechanism by which the new-run flow will obtain the scout concurrency value after the input is gone (e.g. reading `defaultScoutConcurrency` from the Zustand settings store inside `startRun`, or reading it in the component and passing it as before).",
        "The chosen fate of the `/api/start-run` request body -- either it still carries `scout_concurrency` (derived server-side or sent from the settings store) or it stops carrying it (and the backend derives it from config).",
        "Any tests or stories that need to be updated (e.g. a stub scout-concurrency field in NewRunForm stories).",
    ],
    ("koan-1", "scout-concurrency-settings-only", "plan-spec", "overall"): [
        "Specify the removal of the scout-concurrency control from `frontend/src/components/organisms/NewRunForm.tsx` (the `nrf-field` block, the `scoutConcurrency` local state, and its use in the `handleStart` / `api.startRun` call site).",
        "Preserve the existing Settings UI (`SettingsOverlay.tsx` / `SettingsPage.tsx`) -- the plan should NOT also remove the control from Settings.",
        "Specify how `api.startRun` obtains the value afterwards (reads from the settings store, reads from the backend, or the parameter is dropped entirely) -- one clear decision, not a list of maybes.",
        "Leave the backend `koan/config.py` default (`scout_concurrency: int = 8`) intact as the fallback source of truth when no explicit override is provided.",
    ],
    # yolo-flag / intake
    ("koan-1", "yolo-flag", "intake", "summary"): [
        "The existing --yolo usage in the codex and gemini runner paths (`koan/web/app.py` `_YOLO_ARGS`), and the fact that this is unrelated to the user-interaction auto-answering behavior being asked for.",
        'The chosen return-value semantics for `koan_yield` (recommended-progression hint) and `koan_ask_question` (recommended answer or "use your best judgement") in yolo mode.',
        "The chosen UI-event treatment (skip / auto_answered flag / emit-and-resolve-immediately) and rationale.",
        "The corrected framing of the original task description: --yolo is not a no-op globally; it currently has no effect on koan's own interaction gates.",
        "The broader use case (eval automation / unsupervised runs) as the reason the auto-answering behavior is wanted.",
    ],
    ("koan-1", "yolo-flag", "intake", "questions"): [
        'Flagged the inaccuracy in the task description\'s claim "--yolo is currently a no-op": --yolo is already used in the codex and gemini runner paths as an "accept everything" permission mode; the accurate framing is that --yolo currently has no effect on koan\'s own user-interaction gates (`koan_yield`, `koan_ask_question`).',
        "Asked what `koan_yield` should return in yolo mode (recommended behavior: the recommended-progression hint from the yield's suggestions list).",
        'Asked what `koan_ask_question` should return in yolo mode (recommended behavior: the pre-configured recommended answer if one exists, or free-form text such as "use your best judgement").',
        "Asked whether UI events should still be emitted when interactions are auto-answered (acceptable options: skip entirely, emit with an `auto_answered` flag, or emit normally and resolve immediately).",
        "Asked about the broader use case for --yolo as a non-interactive mode (expected answer: running evals in unsupervised mode).",
    ],
    ("koan-1", "yolo-flag", "intake", "overall"): [
        "The orchestrator demonstrated understanding that --yolo is the switch that removes the human from the loop and is intended for automated / eval use, and that adding auto-answering behavior to --yolo is what makes unattended eval runs possible.",
    ],
    # yolo-flag / plan-spec
    ("koan-1", "yolo-flag", "plan-spec", "summary"): [
        "How `koan_yield` responds under yolo (recommended-progression hint from the yield's suggestions list).",
        'How `koan_ask_question` responds under yolo (recommended answer if present, else free-form "use your best judgement").',
        "Whether and how UI events are emitted for auto-answered interactions (skip / `auto_answered` flag / emit normally and resolve immediately).",
        "The file or files touched to implement the auto-answering logic, named specifically.",
    ],
    ("koan-1", "yolo-flag", "plan-spec", "overall"): [
        "Stay scoped to the interaction-gate auto-answering behavior without proposing broader refactors of the runner subsystem, the permission fence, or unrelated CLI surface.",
        'Not contradict the existing --yolo usage -- the plan does not break or regress the existing codex / gemini "accept everything" behavior controlled by `_YOLO_ARGS` in `koan/web/app.py`.',
        "Name the actual auto-response integration point (the `koan_yield` and `koan_ask_question` tool handlers in `koan/web/mcp_endpoint.py`) rather than an invented indirection layer.",
    ],
}


# -- Cross-phase rubric bodies -------------------------------------------------
# Key: (fixture_id, task_id, case_id).
# Value: verbatim body text from case file (after lstrip("\n")).

CROSS_PHASE_RUBRICS: dict[tuple[str, str, str], str] = {
    ("koan-1", "add-logs", "intake-plan-spec"): """\
Grade the consistency and coherence of the complete workflow across all phases.

This rubric evaluates cross-phase quality, not per-phase quality.

Check the following:

- Intake findings are reflected in the plan. The plan.md approach should be traceable to the questions and discoveries from intake -- the decisions made during intake should visibly shape the plan.
- Phase summaries form a coherent chain. The intake summary's conclusions should be consistent with the plan-spec summary's approach. No contradiction between summaries.
- At minimum, both intake and plan-spec phases were observed and produced summaries. A workflow that skipped either phase fails this rubric.
- No hallucinated pivots. The plan does not introduce a completely different approach than what intake suggested, without an explicit rationale.

## Task-specific additions (add-logs)

Beyond the generic cross-phase coherence checks, the plan for the "add logs" task should visibly carry forward the intake-phase decisions on:

- what type of logs: frontend, backend, etc.
- purpose of the logs / problem they're solving
- log level strategy (what constitutes as debug vs info vs warning vs error)
- structured vs unstructured logging

If intake decided a specific behavior for any of these and plan-spec contradicts it without rationale, that is a hallucinated pivot and fails this rubric.

PASS if all four generic criteria are met across the observed phases AND the plan's approach is traceable to the intake decisions on the four add-logs-specific points above.
FAIL if any criterion is violated, or if fewer than two phases are present, or if plan-spec silently diverges from an intake decision.

Respond with PASS or FAIL on the last line.""",

    ("koan-1", "scout-concurrency-settings-only", "intake-plan-spec"): """\
Grade the consistency and coherence of the complete workflow across all phases.

This rubric evaluates cross-phase quality, not per-phase quality.

Check the following:

- Intake findings are reflected in the plan. The plan.md approach should be traceable to the questions and discoveries from intake -- the decisions made during intake should visibly shape the plan.
- Phase summaries form a coherent chain. The intake summary's conclusions should be consistent with the plan-spec summary's approach. No contradiction between summaries.
- At minimum, both intake and plan-spec phases were observed and produced summaries. A workflow that skipped either phase fails this rubric.
- No hallucinated pivots. The plan does not introduce a completely different approach than what intake suggested, without an explicit rationale.

## Task-specific additions (scout-concurrency-settings-only)

Beyond the generic cross-phase coherence checks, the plan for this task should visibly carry forward the intake-phase decisions on:

- How the new-run flow reads the scout concurrency value after the input is removed (the settings store / persisted setting is the expected source; whatever intake decided, plan-spec must match).
- The fate of the API client's per-call `scoutConcurrency` parameter (dropped, kept-optional, or kept-required) -- intake and plan-spec must agree.
- Whether the backend `/api/start-run` request shape changes (still accepts `scout_concurrency`, or stops accepting it) -- intake and plan-spec must agree.

If intake decided a specific behavior for any of these and plan-spec contradicts it without rationale, that is a hallucinated pivot and fails this rubric.

PASS if all four generic criteria are met across the observed phases AND the plan's approach is traceable to the intake decisions on the three points above.
FAIL if any criterion is violated, or if fewer than two phases are present, or if plan-spec silently diverges from an intake decision.

Respond with PASS or FAIL on the last line.""",

    ("koan-1", "yolo-flag", "intake-plan-spec"): """\
Grade the consistency and coherence of the complete workflow across all phases.

This rubric evaluates cross-phase quality, not per-phase quality.

Check the following:

- Intake findings are reflected in the plan. The plan.md approach should be traceable to the questions and discoveries from intake -- the decisions made during intake should visibly shape the plan.
- Phase summaries form a coherent chain. The intake summary's conclusions should be consistent with the plan-spec summary's approach. No contradiction between summaries.
- At minimum, both intake and plan-spec phases were observed and produced summaries. A workflow that skipped either phase fails this rubric.
- No hallucinated pivots. The plan does not introduce a completely different approach than what intake suggested, without an explicit rationale.

## Task-specific additions (yolo-flag)

Beyond the generic cross-phase coherence checks, the plan for the --yolo task should visibly carry forward the intake-phase decisions on:

- `koan_yield` return value in yolo mode.
- `koan_ask_question` return value in yolo mode.
- UI event emission policy for auto-answered interactions.

If intake decided a specific behavior for any of these and plan-spec contradicts it without rationale, that is a hallucinated pivot and fails this rubric.

PASS if all four generic criteria are met across the observed phases AND the plan's approach is traceable to the intake decisions on the three yolo-specific points above.
FAIL if any criterion is violated, or if fewer than two phases are present, or if plan-spec silently diverges from an intake decision.

Respond with PASS or FAIL on the last line.""",
}


# -- Lookup helpers ------------------------------------------------------------

def get_rubric_criteria(
    fixture_id: str, task_id: str, phase: str, section: str,
) -> list[str] | None:
    """Concatenated fixture + task-addendum criteria, or None if neither exists."""
    base = FIXTURE_RUBRICS.get((fixture_id, phase, section))
    addendum = TASK_RUBRIC_ADDENDUMS.get((fixture_id, task_id, phase, section), [])
    if base is None and not addendum:
        return None
    return (base or []) + addendum


def get_cross_phase_rubric(
    fixture_id: str, task_id: str, case_id: str,
) -> str | None:
    """Cross-phase rubric body for the case, or None if absent/empty."""
    body = CROSS_PHASE_RUBRICS.get((fixture_id, task_id, case_id))
    if body is None or not body.strip():
        return None
    return body

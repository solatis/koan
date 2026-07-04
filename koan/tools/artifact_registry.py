# Artifact registry: filename grammar, reviewer classification, and write/edit/execute policy.
#
# Single source of truth for artifact filename validity. Pure module -- no
# filesystem, projection, or run-state reads. Validators accept plain-data
# state as arguments so the module is unit-testable in isolation. M3 wires
# validate_write / validate_edit into koan_artifact_write / koan_artifact_edit;
# M4 adds validate_executor_request for koan_request_executor.
# M5: koan_set_phase is pure routing; execution target validation moved to koan_request_executor.
# M6: removed remediation chain grammar (-remediation-K forms); re-execution edits the
#     same living plan in place so successor names are never produced.
#
# Grammar (all N are positive integers [1-9][0-9]* -- zero and
# leading-zero forms are rejected):
#
#   brief.md
#   core-flows.md
#   tech-plan.md
#   milestones.md
#   plan.md
#   plan-milestone-<N>.md

from __future__ import annotations

import re
from dataclasses import dataclass, field


# -- Dataclasses -------------------------------------------------------------- #


@dataclass(frozen=True)
class ArtifactCoordinate:
    """Decoded artifact identity.

    family:         canonical family name ("plan", "milestones", "brief", etc.)
    discriminator:  milestone N for plan-milestone-N.md; None otherwise.
    """

    family: str
    discriminator: int | None


@dataclass(frozen=True)
class ArtifactRegistryEntry:
    """Policy row for one artifact family.

    family:              canonical family key matching ARTIFACT_REGISTRY.
    create_steps:        frozenset of (phase, step_name) pairs where koan_artifact_write
                         is legal for this family.  step_name is the stable string key
                         from the phase module's STEP_NAMES (e.g. "Summarize").
    edit_steps:          frozenset of (phase, step_name) pairs where koan_artifact_edit
                         is legal for this family.  May differ from create_steps (e.g.
                         milestones.md is also editable during execute/Assess).
    origin_phases:       derived @property -- the set of phases appearing in
                         create_steps, so phase-level legality has a single source.
    reviewer_prompt:     string tag for the reviewer charter
                         ("PLAN_REVIEWER" | "MILESTONE_REVIEWER" | "TECH_PLAN_REVIEWER")
                         or None for families without a reviewer.
    takes_discriminator: whether this family allows/requires a milestone N suffix.
    on_write:            "create_and_review" | "create_no_review"
    on_edit:             "revise_draft" | "bookkeeping"
    """

    family: str
    # Per-step create/edit sets replace the old origin_phases field.
    # origin_phases is now a derived property so phase legality has one source.
    create_steps: frozenset[tuple[str, str]]
    edit_steps: frozenset[tuple[str, str]]
    reviewer_prompt: str | None
    takes_discriminator: bool
    on_write: str
    on_edit: str

    @property
    def origin_phases(self) -> frozenset[str]:
        """Derive the legal-write phase set from create_steps.

        Computed rather than stored so create_steps is the single source of
        truth for phase-level legality -- no risk of divergence between the two.
        """
        return frozenset(phase for phase, _ in self.create_steps)


@dataclass(frozen=True)
class ValidationError:
    """Structured, recoverable validation failure returned by the validators.

    code:           machine key; one of:
                    name_malformed | wrong_phase | out_of_step | exists_draft |
                    not_found |
                    execute_not_found | execute_not_plan |
                    execute_requires_instructions |
                    invalid_transition | unknown_workflow |
                    tool_unavailable_in_phase.
                    M5: koan_set_phase is pure routing; re-execution is the feature.
                    M6: remediation chain concept dropped; no successor-gap code.
                    out_of_step is returned when the artifact family is legal in the
                    current phase but the tool was called outside the step(s) where
                    the operation is permitted.
                    invalid_transition | unknown_workflow are constructed in
                    koan_tools.py for workflow-transition rejections and share this
                    type so they flow through _permission_error_result.
                    tool_unavailable_in_phase is constructed in
                    koan_tools._tool_phase_gate_result for call-time phase-gate
                    denials (koan_request_scouts, koan_request_executor
                    invoked outside their allowed phases).
    message:        human-readable explanation for the orchestrator.
    allowed:        when/where the call IS legal -- the self-correction hint shown to
                    the model so it can re-issue at the right time.  Empty string when
                    no correction hint is applicable.
    suggested_name: nearest legal alternative filename, when derivable.
    """

    code: str
    message: str
    # allowed is after message so existing positional construction still works,
    # and it has a default so existing keyword construction is unaffected.
    allowed: str = ""
    suggested_name: str | None = None


# -- Registry table ----------------------------------------------------------- #

ARTIFACT_REGISTRY: dict[str, ArtifactRegistryEntry] = {
    "brief": ArtifactRegistryEntry(
        family="brief",
        create_steps=frozenset({("intake", "Summarize")}),
        edit_steps=frozenset({("intake", "Summarize")}),
        reviewer_prompt=None,
        takes_discriminator=False,
        on_write="create_no_review",
        on_edit="revise_draft",
    ),
    "core-flows": ArtifactRegistryEntry(
        family="core-flows",
        create_steps=frozenset({("core-flows", "Write")}),
        edit_steps=frozenset({("core-flows", "Write")}),
        reviewer_prompt=None,
        takes_discriminator=False,
        on_write="create_no_review",
        on_edit="revise_draft",
    ),
    "tech-plan": ArtifactRegistryEntry(
        family="tech-plan",
        create_steps=frozenset({("tech-plan", "Write")}),
        edit_steps=frozenset({("tech-plan", "Write")}),
        reviewer_prompt="TECH_PLAN_REVIEWER",
        takes_discriminator=False,
        on_write="create_and_review",
        on_edit="revise_draft",
    ),
    "milestones": ArtifactRegistryEntry(
        family="milestones",
        create_steps=frozenset({("milestone", "Write")}),
        # milestones.md is also editable during execute/Reconcile so the
        # post-execution conformance update path is legal. M5: renamed Assess->Reconcile.
        edit_steps=frozenset({("milestone", "Write"), ("execute", "Reconcile")}),
        reviewer_prompt="MILESTONE_REVIEWER",
        takes_discriminator=False,
        on_write="create_and_review",
        on_edit="bookkeeping",
    ),
    # One "plan" family covers both plan.md (discriminator=None) and
    # plan-milestone-N.md (discriminator=N). The workflow supplies
    # requires_discriminator to validators to distinguish the two legal forms.
    "plan": ArtifactRegistryEntry(
        family="plan",
        create_steps=frozenset({("plan", "Analyze"), ("plan", "Write")}),
        edit_steps=frozenset({("plan", "Analyze"), ("plan", "Write")}),
        reviewer_prompt="PLAN_REVIEWER",
        takes_discriminator=True,
        on_write="create_and_review",
        on_edit="revise_draft",
    ),
}

# Living-document families: editable from any phase the orchestrator runs in.
# The per-step EDIT gate is skipped for these families so the orchestrator may
# revise them ad hoc (reconcile review findings, adjust scope before a re-run).
# CREATE-step gating is unchanged -- artifacts still originate in the right phase.
# Only plan and milestones qualify; brief/core-flows/tech-plan remain per-step gated.
LIVING_DOC_FAMILIES: frozenset[str] = frozenset({"plan", "milestones"})


# -- Filename grammar (anchored regexes) -------------------------------------- #

# Positive integer: [1-9][0-9]* -- rejects 0 and any leading-zero form.
_POS_INT = r"[1-9][0-9]*"

# Exact-base patterns are compiled BEFORE the parametric plan-family patterns to
# avoid the tech-plan-vs-plan prefix hazard: tech-plan.md must be tried first so
# it is never accidentally matched by a "starts with plan" branch.
_EXACT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^brief\.md$"), "brief"),
    (re.compile(r"^core-flows\.md$"), "core-flows"),
    (re.compile(r"^tech-plan\.md$"), "tech-plan"),
    (re.compile(r"^milestones\.md$"), "milestones"),
    (re.compile(r"^plan\.md$"), "plan"),
]

# Parametric plan-family patterns (all anchored; N is a pos-int group).
# M6: remediation grammar patterns removed -- re-execution edits the same living
# plan in place so -remediation-K successors are never produced.
_PLAN_MILESTONE = re.compile(rf"^plan-milestone-({_POS_INT})\.md$")

# -- Grammar parser ----------------------------------------------------------- #


def parse_artifact_filename(filename: str) -> ArtifactCoordinate | None:
    """Decode *filename* into an ArtifactCoordinate, or return None.

    Recognizes (in matching order -- exact bases before plan patterns):
      brief.md            -> (brief, None)
      core-flows.md       -> (core-flows, None)
      tech-plan.md        -> (tech-plan, None)
      milestones.md       -> (milestones, None)
      plan.md             -> (plan, None)
      plan-milestone-N.md -> (plan, N)

    N is a positive integer ([1-9][0-9]*). Returns None for .review.md
    sidecars, zero/leading-zero indices, and anything else not matching the grammar.
    M6: plan-remediation-K.md and plan-milestone-N-remediation-K.md are no longer
    recognized -- they return None (name_malformed if a write is attempted).
    """
    # Try exact non-parametric bases first.
    for pattern, family in _EXACT:
        if pattern.match(filename):
            return ArtifactCoordinate(family=family, discriminator=None)

    # plan-milestone-N.md
    m = _PLAN_MILESTONE.match(filename)
    if m:
        return ArtifactCoordinate(family="plan", discriminator=int(m.group(1)))

    return None


# -- Classification helpers --------------------------------------------------- #


def classify(family: str) -> ArtifactRegistryEntry | None:
    """Look up the registry entry for *family*, or return None if unknown."""
    return ARTIFACT_REGISTRY.get(family)


def reviewer_for(filename: str) -> str | None:
    """Return the reviewer_prompt tag for *filename*, or None.

    Returns None for unrecognized filenames, families without a reviewer,
    and .review.md sidecars.
    """
    coord = parse_artifact_filename(filename)
    if coord is None:
        return None
    entry = classify(coord.family)
    if entry is None:
        return None
    return entry.reviewer_prompt


# -- Validators --------------------------------------------------------------- #


def validate_write(
    filename: str,
    *,
    phase: str,
    requires_discriminator: bool,
    existing_names: frozenset[str],
    step_name: str | None = None,
) -> ValidationError | None:
    """Validate a proposed artifact write. Returns None on success.

    Error codes (in order of precedence):
      name_malformed    -- filename not in grammar.
      wrong_phase       -- family not legal in the current phase, or discriminator
                          form mismatch (bare plan.md when requires_discriminator,
                          or discriminated plan-milestone-N.md when not).
      out_of_step       -- phase is legal but the tool was called outside the
                          step(s) where creating this artifact family is permitted.
                          Only checked when step_name is truthy (fail-open: when
                          step_name is None/empty the check is skipped so missing
                          step metadata never causes a false rejection).
      exists_draft      -- file exists and is an editable draft.
    """
    coord = parse_artifact_filename(filename)
    if coord is None:
        return ValidationError(
            code="name_malformed",
            message=(
                f"{filename!r} does not match the artifact grammar. "
                "Expected one of: brief.md, core-flows.md, tech-plan.md, milestones.md, "
                "plan.md, plan-milestone-N.md (N is a positive integer)."
            ),
        )

    entry = classify(coord.family)
    if entry is None:
        # Should not happen given a well-formed coordinate, but be defensive.
        return ValidationError(
            code="name_malformed",
            message=f"Unknown family {coord.family!r} decoded from {filename!r}.",
        )

    if phase not in entry.origin_phases:
        legal_phases = ", ".join(sorted(entry.origin_phases))
        return ValidationError(
            code="wrong_phase",
            message=(
                f"{filename!r} (family {coord.family!r}) may only be written in phase(s) "
                f"{legal_phases!r}; current phase is {phase!r}."
            ),
        )

    # Per-step check: fail-open when step_name is unresolved (None/empty) so
    # missing step metadata never causes a false rejection.
    if step_name and entry.create_steps and (phase, step_name) not in entry.create_steps:
        legal = ", ".join(
            f"{p}/{s}" for p, s in sorted(entry.create_steps)
        )
        return ValidationError(
            code="out_of_step",
            message=(
                f"{filename!r} (family {coord.family!r}) may only be created in step(s) "
                f"{legal!r}; current position is phase={phase!r}, step={step_name!r}."
            ),
            allowed=f"Write {filename!r} in one of these (phase, step) positions: {legal}.",
        )

    # For the plan family, validate that the discriminator form matches the workflow.
    if coord.family == "plan":
        if requires_discriminator and coord.discriminator is None:
            # Bare plan.md is wrong; this workflow fans out to milestones.
            return ValidationError(
                code="wrong_phase",
                message=(
                    "The current workflow requires a discriminated plan name "
                    "(plan-milestone-N.md). Bare plan.md is not legal here."
                ),
                suggested_name="plan-milestone-1.md",
            )
        if not requires_discriminator and coord.discriminator is not None:
            # Discriminated plan-milestone-N.md is wrong; this workflow uses bare plan.md.
            return ValidationError(
                code="wrong_phase",
                message=(
                    "The current workflow uses a bare plan (plan.md). "
                    f"Discriminated {filename!r} is not legal here."
                ),
                suggested_name="plan.md",
            )

    if filename in existing_names:
        return ValidationError(
            code="exists_draft",
            message=(
                f"{filename!r} already exists as an editable draft. "
                "Use koan_artifact_edit to revise it, or write a different name."
            ),
            allowed="Use koan_artifact_edit to revise it.",
        )

    return None


def validate_edit(
    filename: str,
    *,
    existing_names: frozenset[str],
    phase: str | None = None,
    step_name: str | None = None,
) -> ValidationError | None:
    """Validate a proposed artifact edit. Returns None on success.

    phase and step_name are optional; when either is falsy the per-step check
    is skipped (fail-open).  The caller (artifact_edit_core) resolves them from
    the current run state and the phase module's STEP_NAMES.

    Living-document families (plan, milestones) are exempt from the per-step
    edit gate: they may be edited from any phase the orchestrator runs in.
    All other families (brief, core-flows, tech-plan) remain per-step gated.

    Error codes (in precedence order):
      not_found   -- file does not exist; suggested_name="write".
      out_of_step -- file exists but the edit is called outside the step(s)
                     where editing this family is permitted.  Only checked when
                     both phase and step_name are truthy, and only for
                     non-living-document families.
    """
    if filename not in existing_names:
        return ValidationError(
            code="not_found",
            message=f"{filename!r} does not exist. Use koan_artifact_write to create it.",
            suggested_name="write",
        )

    # Per-step edit check: fail-open when phase or step_name is unresolved.
    # Living-document families (plan, milestones) are exempt: they are mutable
    # working surfaces editable from any phase (M2 relaxation).
    if phase and step_name:
        coord = parse_artifact_filename(filename)
        if coord is not None and coord.family not in LIVING_DOC_FAMILIES:
            entry = classify(coord.family)
            if entry is not None and entry.edit_steps and (phase, step_name) not in entry.edit_steps:
                legal = ", ".join(
                    f"{p}/{s}" for p, s in sorted(entry.edit_steps)
                )
                return ValidationError(
                    code="out_of_step",
                    message=(
                        f"{filename!r} (family {coord.family!r}) may only be edited in "
                        f"step(s) {legal!r}; current position is phase={phase!r}, "
                        f"step={step_name!r}."
                    ),
                    allowed=f"Edit {filename!r} in one of these (phase, step) positions: {legal}.",
                )

    return None



def validate_executor_request(
    plan_file: str | None,
    instructions: str | None,
    *,
    existing_names: frozenset[str],
) -> ValidationError | None:
    """Validate a koan_request_executor call. Returns None on success.

    Re-execution is intentionally allowed: the same plan may be run multiple
    times. M5: there is no re-execution gate here.

    Error codes (in order of precedence):
      execute_requires_instructions -- neither plan_file nor non-blank instructions given.
      execute_not_found             -- plan_file is not in grammar or not in existing_names.
      execute_not_plan              -- plan_file exists but is not a plan-family artifact.
    """
    # A run with neither a plan nor instructions has nothing to direct the executor.
    if not plan_file and not (instructions and instructions.strip()):
        return ValidationError(
            code="execute_requires_instructions",
            message=(
                "koan_request_executor requires either a plan_file or free-form "
                "instructions (or both). A run with neither has nothing to direct "
                "the executor."
            ),
            allowed="Provide a plan_file naming an existing plan artifact, or supply free-form instructions.",
        )

    if plan_file is not None:
        coord = parse_artifact_filename(plan_file)
        if coord is None or plan_file not in existing_names:
            return ValidationError(
                code="execute_not_found",
                message=(
                    f"{plan_file!r} was not found in the run directory. "
                    "Provide the exact filename of an existing plan artifact."
                ),
                allowed="Provide the exact filename of an existing plan artifact in the run directory.",
            )
        if coord.family != "plan":
            return ValidationError(
                code="execute_not_plan",
                message=(
                    f"{plan_file!r} is a {coord.family!r} artifact; "
                    "only plan-family artifacts may be named for execution."
                ),
                allowed="Name a plan-family artifact (plan.md or plan-milestone-N.md) for execution.",
            )

    return None

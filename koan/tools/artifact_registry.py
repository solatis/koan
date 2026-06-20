# Artifact registry: filename grammar, reviewer classification, and write/edit/execute policy.
#
# Single source of truth for artifact filename validity. Pure module -- no
# filesystem, projection, or run-state reads. Validators accept plain-data
# state as arguments so the module is unit-testable in isolation. M3 wires
# validate_write / validate_edit into koan_artifact_write / koan_artifact_edit;
# M4 wires validate_execute_target into the execute-handoff path.
#
# Grammar (all N and K are positive integers [1-9][0-9]* -- zero and
# leading-zero forms are rejected):
#
#   brief.md
#   core-flows.md
#   tech-plan.md
#   milestones.md
#   plan.md
#   plan-milestone-<N>.md
#   plan-remediation-<K>.md
#   plan-milestone-<N>-remediation-<K>.md
#   <reviewable>.review.md           -- koan-owned sidecar; never in registry

from __future__ import annotations

import re
from dataclasses import dataclass, field


# -- Dataclasses -------------------------------------------------------------- #


@dataclass(frozen=True)
class ArtifactCoordinate:
    """Decoded artifact identity.

    family:          canonical family name ("plan", "milestones", "brief", etc.)
    discriminator:   milestone N for plan-milestone-N.md; None otherwise.
    chain_position:  remediation index K for -remediation-K successors; None otherwise.
    """

    family: str
    discriminator: int | None
    chain_position: int | None


@dataclass(frozen=True)
class ArtifactRegistryEntry:
    """Policy row for one artifact family.

    family:              canonical family key matching ARTIFACT_REGISTRY.
    origin_phases:       set of phase ids in which a write of this family is legal.
    reviewer_prompt:     string tag for the reviewer charter
                         ("PLAN_REVIEWER" | "MILESTONE_REVIEWER" | "TECH_PLAN_REVIEWER")
                         or None for families without a reviewer.
    takes_discriminator: whether this family allows/requires a milestone N suffix.
    takes_chain:         whether -remediation-K successors are legal for this family.
    on_write:            "create_and_review" | "create_no_review"
    on_edit:             "revise_draft" | "bookkeeping"
    """

    family: str
    origin_phases: frozenset[str]
    reviewer_prompt: str | None
    takes_discriminator: bool
    takes_chain: bool
    on_write: str
    on_edit: str


@dataclass(frozen=True)
class ValidationError:
    """Structured, recoverable validation failure returned by the validators.

    code:           machine key; one of:
                    name_malformed | wrong_phase | exists_draft | exists_frozen |
                    chain_gap | not_found | frozen |
                    execute_not_found | execute_not_plan | already_executed
    message:        human-readable explanation for the orchestrator.
    suggested_name: nearest legal alternative filename, when derivable.
    """

    code: str
    message: str
    suggested_name: str | None = None


# -- Registry table ----------------------------------------------------------- #

# The .review.md sidecar is deliberately NOT in this registry: a direct write
# is koan-rejected, edit is the trusted append path, and the sidecar is never
# classified as reviewable -- no recursive reviewer spawns.
ARTIFACT_REGISTRY: dict[str, ArtifactRegistryEntry] = {
    "brief": ArtifactRegistryEntry(
        family="brief",
        origin_phases=frozenset({"intake"}),
        reviewer_prompt=None,
        takes_discriminator=False,
        takes_chain=False,
        on_write="create_no_review",
        on_edit="revise_draft",
    ),
    "core-flows": ArtifactRegistryEntry(
        family="core-flows",
        origin_phases=frozenset({"core-flows"}),
        reviewer_prompt=None,
        takes_discriminator=False,
        takes_chain=False,
        on_write="create_no_review",
        on_edit="revise_draft",
    ),
    "tech-plan": ArtifactRegistryEntry(
        family="tech-plan",
        origin_phases=frozenset({"tech-plan"}),
        reviewer_prompt="TECH_PLAN_REVIEWER",
        takes_discriminator=False,
        takes_chain=False,
        on_write="create_and_review",
        on_edit="revise_draft",
    ),
    "milestones": ArtifactRegistryEntry(
        family="milestones",
        origin_phases=frozenset({"milestone"}),
        reviewer_prompt="MILESTONE_REVIEWER",
        takes_discriminator=False,
        takes_chain=False,
        on_write="create_and_review",
        on_edit="bookkeeping",
    ),
    # One "plan" family covers both plan.md (discriminator=None) and
    # plan-milestone-N.md (discriminator=N). The workflow supplies
    # requires_discriminator to validators to distinguish the two legal forms.
    "plan": ArtifactRegistryEntry(
        family="plan",
        origin_phases=frozenset({"plan"}),
        reviewer_prompt="PLAN_REVIEWER",
        takes_discriminator=True,
        takes_chain=True,
        on_write="create_and_review",
        on_edit="revise_draft",
    ),
}

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

# Parametric plan-family patterns (all anchored; N and K are pos-int groups).
_PLAN_MILESTONE_REMEDIATION = re.compile(
    rf"^plan-milestone-({_POS_INT})-remediation-({_POS_INT})\.md$"
)
_PLAN_MILESTONE = re.compile(rf"^plan-milestone-({_POS_INT})\.md$")
_PLAN_REMEDIATION = re.compile(rf"^plan-remediation-({_POS_INT})\.md$")

# Sidecar pattern: any filename ending in .review.md.
_REVIEW_SIDECAR = re.compile(r"^.+\.review\.md$")


# -- Grammar parser ----------------------------------------------------------- #


def parse_artifact_filename(filename: str) -> ArtifactCoordinate | None:
    """Decode *filename* into an ArtifactCoordinate, or return None.

    Recognizes (in matching order -- exact bases before plan patterns):
      brief.md              -> (brief, None, None)
      core-flows.md         -> (core-flows, None, None)
      tech-plan.md          -> (tech-plan, None, None)
      milestones.md         -> (milestones, None, None)
      plan.md               -> (plan, None, None)
      plan-milestone-N.md   -> (plan, N, None)
      plan-remediation-K.md -> (plan, None, K)
      plan-milestone-N-remediation-K.md -> (plan, N, K)

    N and K are positive integers ([1-9][0-9]*). Returns None for .review.md
    sidecars, zero/leading-zero indices, and anything else not matching the grammar.
    """
    # Try exact non-parametric bases first.
    for pattern, family in _EXACT:
        if pattern.match(filename):
            return ArtifactCoordinate(family=family, discriminator=None, chain_position=None)

    # plan-milestone-N-remediation-K.md (must precede the two single-group forms)
    m = _PLAN_MILESTONE_REMEDIATION.match(filename)
    if m:
        return ArtifactCoordinate(
            family="plan",
            discriminator=int(m.group(1)),
            chain_position=int(m.group(2)),
        )

    # plan-milestone-N.md
    m = _PLAN_MILESTONE.match(filename)
    if m:
        return ArtifactCoordinate(family="plan", discriminator=int(m.group(1)), chain_position=None)

    # plan-remediation-K.md
    m = _PLAN_REMEDIATION.match(filename)
    if m:
        return ArtifactCoordinate(family="plan", discriminator=None, chain_position=int(m.group(1)))

    return None


# -- Sidecar helpers ---------------------------------------------------------- #


def is_review_sidecar(filename: str) -> bool:
    """Return True iff *filename* is a review sidecar (ends in .review.md)."""
    return bool(_REVIEW_SIDECAR.match(filename))


def sidecar_name_for(filename: str) -> str:
    """Return the sidecar filename for a reviewable artifact.

    Strips the trailing .md extension and appends .review.md.
    E.g. plan-milestone-1.md -> plan-milestone-1.review.md.
    The caller is responsible for passing a reviewable artifact name.
    """
    stem = filename[: -len(".md")]
    return f"{stem}.review.md"


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


# -- Lineage helpers ---------------------------------------------------------- #


def next_remediation_name(filename: str) -> str | None:
    """Return the next contiguous remediation filename for a plan artifact.

    Given a base plan name, returns -remediation-1.md; given an existing
    remediation, increments K by one. Returns None for non-plan families.

    Examples:
      plan.md                              -> plan-remediation-1.md
      plan-milestone-1.md                  -> plan-milestone-1-remediation-1.md
      plan-remediation-2.md                -> plan-remediation-3.md
      plan-milestone-1-remediation-2.md    -> plan-milestone-1-remediation-3.md
    """
    coord = parse_artifact_filename(filename)
    if coord is None or coord.family != "plan":
        return None

    next_k = (coord.chain_position or 0) + 1

    # Reconstruct the base (family + optional discriminator), then append chain.
    if coord.discriminator is not None:
        base = f"plan-milestone-{coord.discriminator}"
    else:
        base = "plan"

    return f"{base}-remediation-{next_k}.md"


def predecessor_chain(filename: str, all_names: list[str]) -> list[str]:
    """Return the ordered list of predecessor artifacts present in *all_names*.

    For a remediation at chain position K, returns the base plan and each
    -remediation-1 ... -remediation-(K-1) that appears in *all_names*, in
    ascending chain order. Returns an empty list for a base plan (no predecessors)
    or an unrecognized filename.

    The lookup is purely filename-based -- no filesystem access.
    """
    coord = parse_artifact_filename(filename)
    if coord is None or coord.family != "plan" or coord.chain_position is None:
        # Base plan has no predecessors; non-plan or unrecognized -> empty.
        return []

    names_set = set(all_names)
    chain: list[str] = []

    # Base plan name (chain_position=None).
    if coord.discriminator is not None:
        base_name = f"plan-milestone-{coord.discriminator}.md"
    else:
        base_name = "plan.md"

    if base_name in names_set:
        chain.append(base_name)

    # Intermediate remediations 1 .. K-1.
    for k in range(1, coord.chain_position):
        if coord.discriminator is not None:
            pred = f"plan-milestone-{coord.discriminator}-remediation-{k}.md"
        else:
            pred = f"plan-remediation-{k}.md"
        if pred in names_set:
            chain.append(pred)

    return chain


# -- Validators --------------------------------------------------------------- #


def validate_write(
    filename: str,
    *,
    phase: str,
    requires_discriminator: bool,
    existing_names: frozenset[str],
    frozen_names: frozenset[str],
) -> ValidationError | None:
    """Validate a proposed artifact write. Returns None on success.

    Error codes (in order of precedence):
      name_malformed    -- .review.md sidecar write, or filename not in grammar.
      wrong_phase       -- family not legal in the current phase, or discriminator
                          form mismatch (bare plan.md when requires_discriminator,
                          or discriminated plan-milestone-N.md when not).
      exists_frozen     -- file exists and is frozen; suggested_name = next remediation.
      exists_draft      -- file exists and is an editable draft.
      chain_gap         -- remediation K is not contiguous (K-1 does not exist).
    """
    # Reject direct .review.md writes: sidecars are koan-owned.
    if is_review_sidecar(filename):
        return ValidationError(
            code="name_malformed",
            message=(
                f"{filename!r} is a review sidecar; koan creates and owns .review.md files. "
                "Write the primary artifact instead."
            ),
        )

    coord = parse_artifact_filename(filename)
    if coord is None:
        return ValidationError(
            code="name_malformed",
            message=(
                f"{filename!r} does not match the artifact grammar. "
                "Expected one of: brief.md, core-flows.md, tech-plan.md, milestones.md, "
                "plan.md, plan-milestone-N.md, plan-remediation-K.md, "
                "plan-milestone-N-remediation-K.md (N and K are positive integers)."
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

    # For the plan family, validate that the discriminator form matches the workflow.
    if coord.family == "plan":
        if requires_discriminator and coord.discriminator is None and coord.chain_position is None:
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

    # Check existence before chain gap so a frozen-exists error takes priority.
    if filename in existing_names and filename in frozen_names:
        return ValidationError(
            code="exists_frozen",
            message=(
                f"{filename!r} is frozen and cannot be overwritten. "
                "Write a remediation successor instead."
            ),
            suggested_name=next_remediation_name(filename),
        )

    if filename in existing_names:
        return ValidationError(
            code="exists_draft",
            message=(
                f"{filename!r} already exists as an editable draft. "
                "Use koan_artifact_edit to revise it, or write a different name."
            ),
        )

    # Validate remediation contiguity: -remediation-K requires -remediation-(K-1)
    # (or the base plan for K=1) to exist.
    if coord.chain_position is not None and coord.chain_position > 1:
        if coord.discriminator is not None:
            prev = f"plan-milestone-{coord.discriminator}-remediation-{coord.chain_position - 1}.md"
        else:
            prev = f"plan-remediation-{coord.chain_position - 1}.md"
        if prev not in existing_names:
            return ValidationError(
                code="chain_gap",
                message=(
                    f"{filename!r} has chain position {coord.chain_position} but its "
                    f"predecessor {prev!r} does not exist. Remediations must be contiguous."
                ),
                suggested_name=prev,
            )

    return None


def validate_edit(
    filename: str,
    *,
    existing_names: frozenset[str],
    frozen_names: frozenset[str],
) -> ValidationError | None:
    """Validate a proposed artifact edit. Returns None on success.

    .review.md sidecars are always editable (the append path, exempt from the
    frozen check) -- return None immediately for them.

    Error codes:
      not_found  -- file does not exist; suggested_name="write".
      frozen     -- file is frozen; suggested_name = next remediation name.
    """
    # Sidecar append path: always allowed regardless of freeze state.
    if is_review_sidecar(filename):
        return None

    if filename not in existing_names:
        return ValidationError(
            code="not_found",
            message=f"{filename!r} does not exist. Use koan_artifact_write to create it.",
            suggested_name="write",
        )

    if filename in frozen_names:
        return ValidationError(
            code="frozen",
            message=(
                f"{filename!r} is frozen and cannot be edited. "
                "Write a remediation successor instead."
            ),
            suggested_name=next_remediation_name(filename),
        )

    return None


def validate_execute_target(
    filename: str,
    *,
    existing_names: frozenset[str],
    executed_names: frozenset[str],
) -> ValidationError | None:
    """Validate a proposed execute-handoff target. Returns None on success.

    Error codes:
      execute_not_found   -- filename not in grammar or does not exist.
      execute_not_plan    -- file exists but is not a plan-family artifact.
      already_executed    -- plan was already executed; suggested_name = next remediation.
    """
    coord = parse_artifact_filename(filename)
    if coord is None or filename not in existing_names:
        return ValidationError(
            code="execute_not_found",
            message=(
                f"{filename!r} was not found in the run directory. "
                "Provide the exact filename of an existing plan artifact."
            ),
        )

    if coord.family != "plan":
        return ValidationError(
            code="execute_not_plan",
            message=(
                f"{filename!r} is a {coord.family!r} artifact; "
                "only plan-family artifacts may be named for execution."
            ),
        )

    if filename in executed_names:
        return ValidationError(
            code="already_executed",
            message=(
                f"{filename!r} has already been executed. "
                "Write a remediation successor to retry."
            ),
            suggested_name=next_remediation_name(filename),
        )

    return None

# Eval Fixtures

Each subdirectory is one benchmark fixture. A fixture owns a project snapshot
and a set of rubrics. One fixture may host multiple tasks.

## Directory layout

    <fixture>/
        repo/                       -- git submodule pinned to a specific commit of the target project
        rubrics/
            <phase>/
                summary.md          -- grades the phase summary
                questions.md        -- grades questions asked during the phase
                artifacts.md        -- grades files created/modified during the phase
                overall.md          -- grades the phase holistically
        tasks/
            <task>/
                task.md             -- task description (UTF-8 plain text)
                rubrics/            -- optional task-level per-phase rubric addenda (invariant across directed-phase variants)
                    <phase>/
                        <section>.md
                cases/              -- one markdown file per test case; each defines a workflow, a directed phase sequence, and a cross-cutting rubric
                    <slug>.md

## Rubric sections

Each phase supports four sections: `summary`, `questions`, `artifacts`, `overall`.

Cross-cutting / overall rubrics live in case files under `tasks/<task>/cases/<slug>.md`.

## Test cases

Each file under `tasks/<task>/cases/` is a test case. It is a markdown file
with YAML frontmatter followed by the cross-cutting rubric body.

Frontmatter schema:

    ---
    workflow: plan              # string -- which koan workflow to run
    directed_phases:            # list[str] -- phase sequence, last entry must be "done"
      - intake
      - plan-spec
      - done
    ---

The body below the closing `---` is the cross-cutting rubric used by the
`test_workflow_overall` test. It must end with:
`Respond with PASS or FAIL on the last line.`

Phase-scoring semantics: a per-phase test grades only if the phase appears
in the case's `directed_phases`. Tests for phases absent from the list are
skipped even when a rubric file exists on disk.

## Rubric layering

At grade time the scorer concatenates the fixture-level rubric (required) with
the optional task-level rubric addendum. Fixture rubric comes first; task
addendum is appended. If neither exists for a (phase, section) pair, the scorer
is skipped for that sample (no score recorded, not a FAIL).

Every per-phase rubric file must end with: `Respond with PASS or FAIL on the last line.`

## Artifact content limitation

Artifact content in the `artifacts` payload is read from disk at workflow
completion, not per-phase. Files modified in a later phase will show their
final content, not the content they had at the end of the phase that created
them. This is acceptable for the initial scope (intake + plan-spec) because:

- intake produces no artifacts
- plan-spec produces plan.md, which execute may modify -- but the initial
  eval scope does not run execute

## Authoring tips

- Keep rubrics tightly scoped. A rubric that checks one thing is more
  reliably graded by the judge LLM than one that checks five.
- Phrase criteria as observable facts ("plan.md is present in all_present")
  rather than subjective judgments ("the plan is good").
- End every rubric with exactly: `Respond with PASS or FAIL on the last line.`

## Hydrating fixtures

Each fixture's `repo/` directory is a git submodule. After cloning, run:

    git submodule update --init --recursive

to hydrate all submodules. Without this the runner sees an empty directory
and starts koan against an empty project, producing no artifacts.

## Bumping a fixture snapshot

To advance a fixture to a newer commit, check out the desired SHA inside
the submodule and stage the updated pointer:

    git -C evals/fixtures/<name>/repo checkout <sha>
    git add evals/fixtures/<name>/repo
    git commit -m "chore: bump <name> fixture to <sha>"

# Eval Fixtures

Each subdirectory is one benchmark fixture. A fixture owns a project snapshot
and a set of rubrics. One fixture may host multiple tasks.

## Directory layout

    <fixture>/
        snapshot.tar.gz             -- git archive of the target project at a specific commit
        rubrics/
            overall.md              -- workflow-level cross-cutting rubric
            <phase>/
                summary.md          -- grades the phase summary
                questions.md        -- grades questions asked during the phase
                artifacts.md        -- grades files created/modified during the phase
                overall.md          -- grades the phase holistically
        tasks/
            <task>/
                task.md             -- task description (UTF-8 plain text)
                rubrics/            -- optional task-level rubric addenda
                    <phase>/
                        <section>.md

## Rubric sections

Each phase supports four sections: `summary`, `questions`, `artifacts`, `overall`.

There is also a workflow-level rubric at `rubrics/overall.md` that grades
cross-phase consistency.

## Rubric layering

At grade time the scorer concatenates the fixture-level rubric (required) with
the optional task-level rubric addendum. Fixture rubric comes first; task
addendum is appended. If neither exists for a (phase, section) pair, the scorer
is skipped for that sample (no score recorded, not a FAIL).

Every rubric file must end with: `Respond with PASS or FAIL on the last line.`

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

## Hydrating snapshots

`snapshot.tar.gz` is stored via git-lfs. Run:

    git lfs install
    git lfs pull

to hydrate the tarballs before running evals. Without this the solver fails
with a "not a gzip file" error because the checkout contains LFS pointer files.

The snapshot is a `git archive` of the project, so `.koan/memory/*.md` rides
along inside it. No separate memory copy is needed.

To capture a new snapshot from the koan project:

    git archive HEAD --format=tar.gz -o evals/fixtures/<name>/snapshot.tar.gz

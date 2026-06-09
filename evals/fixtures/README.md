# Eval Fixtures

Each subdirectory is one benchmark fixture. A fixture owns a project snapshot
and a set of rubrics. One fixture may host multiple tasks.

## Directory layout

    <fixture>/
        repo/                       -- git submodule pinned to a specific commit of the target project
        tasks/
            <task>/
                task.md             -- task description (UTF-8 plain text, consumed as LLMTestCase.input)

Rubric criteria and case definitions are code-resident in `evals/rubrics.py`
and `evals/cases.py` respectively. There are no rubric `.md` files on disk.

## Rubric sections

Each phase supports four sections: `summary`, `questions`, `artifacts`, `overall`.
Rubric criteria for each section live in `evals/rubrics.py` as Python lists.

Cross-phase rubric bodies also live in `evals/rubrics.py` (`CROSS_PHASE_RUBRICS`).

## Test cases

Test cases are defined in `evals/cases.py` as a `CASES: list[Case]` constant.
Each `Case` specifies a fixture, task, case ID, workflow, and directed phase
sequence. Adding a new case means appending to `CASES` and adding matching
rubric data to `evals/rubrics.py`.

Phase-scoring semantics: a per-phase test grades only if the phase appears
in the case's `directed_phases`. Tests for phases absent from the list are
not collected.

## Rubric layering

At grade time the scorer concatenates the fixture-level rubric (required) with
the optional task-level rubric addendum. Fixture rubric comes first; task
addendum is appended. If neither exists for a (phase, section) pair, the scorer
is skipped for that sample (no score recorded, not a FAIL).

## Per-section rubric format

Per-section rubric files (under `rubrics/<phase>/<section>.md`) must list each
evaluation criterion as exactly one bullet line starting with `- ` or `* `.
Each criterion becomes a single `DAGMetric` (one `BinaryJudgementNode` root)
that judges `ACTUAL_OUTPUT` against that criterion in isolation. Prose
paragraphs and blank lines are ignored by the extractor.

**Rules for per-section rubric files:**

- Each criterion must be a single bullet line -- do NOT combine multiple
  criteria with "and" or list sub-items under one bullet.
- Do NOT end per-section rubric files with `Respond with PASS or FAIL on
  the last line.` -- that directive is for cross-phase case-body rubrics only.
- Self-contained bullets: do not use "see above" or "the preceding list" in
  a bullet; each criterion is sent to the judge in isolation.

**Exception:** case-body rubrics under `tasks/<task>/cases/<slug>.md` are
judged holistically by a single `DAGMetric` whose `BinaryJudgementNode`
receives the full body as `criteria=`. These files retain the
`Respond with PASS or FAIL on the last line.` directive.

## Dimensional metric set

The eval harness produces one `DAGMetric` per criterion per rubric row, plus
one holistic `DAGMetric` per cross-phase case, plus three programmatic metrics
per run row:

| Metric name pattern                        | Type            | What it measures                                  |
|--------------------------------------------|-----------------|---------------------------------------------------|
| `Fixture_{phase}_{section}_{NN} [DAG]`     | DAGMetric       | One fixture-level rubric criterion                |
| `Task_{task}_{phase}_{section}_{NN} [DAG]` | DAGMetric       | One task-addendum rubric criterion                |
| `CrossPhaseCoherence_{task}_{case} [DAG]`  | DAGMetric       | Holistic cross-phase coherence (full rubric body) |
| `Duration`                                 | Programmatic    | Wall-clock seconds for the full run              |
| `TokenCost`                                | Programmatic    | Total input + output tokens (orchestrator only)  |
| `ToolCallCount`                            | Programmatic    | Total tool calls across all phases               |

DAGMetrics require a live LLM judge call
(via `JUDGE_MODEL = GeminiModel("gemini-3-pro-preview")`). The three
programmatic metrics read from `additional_metadata` and need no judge call.

## Artifact content limitation

Artifact content in the `artifacts` payload is read from disk at workflow
completion, not per-phase. Files modified in a later phase will show their
final content, not the content they had at the end of the phase that created
them. This is acceptable for the initial scope (intake + plan-spec) because:

- intake produces no artifacts
- plan-spec produces plan.md, which execute may modify -- but the initial
  eval scope does not run execute

## Test invocation

The test module `tests/evals/test_koan.py` defines two parametrized pytest
functions: `test_rubric` (one row per (case, phase, section) tuple with rubric
criteria) and `test_run` (one row per case). Each row calls `assert_test` with
per-row `DAGMetric` instances constructed at collection time.

Run via: `deepeval test run tests/evals/test_koan.py`
(Plain `pytest` works for collection but does not upload to Confident AI and
does not attach hyperparameters.)

## Authoring tips

- Keep rubrics tightly scoped. A rubric bullet that checks one thing is more
  reliably graded by the judge LLM than one that checks five.
- Phrase criteria as observable facts ("plan.md is present in all_present")
  rather than subjective judgments ("the plan is good").
- End every case-body rubric with exactly: `Respond with PASS or FAIL on the last line.`
- Do NOT end per-section rubric files with that directive.

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

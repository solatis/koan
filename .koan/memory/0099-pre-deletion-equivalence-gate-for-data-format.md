---
title: Pre-deletion equivalence gate for data-format migrations
type: procedure
created: '2026-04-24T05:48:42Z'
modified: '2026-04-24T05:48:42Z'
related:
- 0089-proactively-capture-memory-updates-for-discovered.md
---

This entry records a procedure for koan data-format migrations, established on 2026-04-24 during the rubric and case-data move from `evals/fixtures/**/*.md` to Python module constants in `evals/rubrics.py` and `evals/cases.py`. Leon adopted the rule: when migrating data from one storage representation to another, before deleting the source representation a one-shot equivalence script must verify that the target representation matches the source byte-for-byte. The script's exit code is the gate -- exit 0 unblocks deletion; any non-zero exit code halts the migration for investigation and target-representation revision.

Concrete implementation for the 2026-04-24 migration: `evals/_verify_rubric_migration.py` walked every `.md` file on disk (8 fixture-level rubrics matched via `fixtures/*/rubrics/*/*.md`, 14 task-level addendum rubrics via `fixtures/*/tasks/*/rubrics/*/*.md`, 3 case-file bodies via `fixtures/*/tasks/*/cases/*.md`), ran the same bullet-extraction logic (`line.lstrip().startswith(("- ", "* "))` -> strip prefix and trailing whitespace) that produced the in-code dict values, and compared element-by-element. For cross-phase rubrics the comparison was `body.rstrip()` vs `CROSS_PHASE_RUBRICS[key].rstrip()`. Mismatches were printed as `MISMATCH <kind> <key>: disk=N, code=M` lines; zero mismatches means exit 0. The script was written BEFORE any `.md` file was deleted and invoked as `python -m evals._verify_rubric_migration`.

Rationale: mechanical transcription of bulk data is error-prone. Without an explicit equivalence gate, silent content drift between source and target (a missing bullet, a paraphrased criterion, a normalized whitespace character, a truncated body) is invisible until an eval judge scores against subtly different criteria than the original rubric. On 2026-04-24 Leon stated the position explicitly: do not trust the executor's transcription; verify against the source before destroying the source. Applicable scope: any migration where silent content drift during mechanical transcription would be a hazard -- YAML-to-code, JSON-to-Python-dataclass, docstring-to-structured-metadata, etc. The script itself is a throwaway migration aid; retention after migration is optional but supports re-migration if the source representation is ever reintroduced.

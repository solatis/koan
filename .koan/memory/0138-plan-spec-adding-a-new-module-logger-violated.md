---
title: A plan adding a new module logger violated brief.md Out of Scope; review caught
  it by walking the Out of Scope list line by line
type: lesson
created: '2026-05-04T07:56:15Z'
modified: '2026-06-20T00:41:30Z'
related:
- 0117-plan-review-reviewer-scope-narrowed-drop.md
- 0118-plan-spec-and-plan-review-require-implementation.md
- 0145-plan-review-must-walk-briefmd-decisions-and.md
- 0225-koan-review-and-execution-are-triggered.md
---

A koan plan workflow on 2026-05-04 (steering observability and naming hygiene) produced a planning failure. Intake had explicitly enumerated in `brief.md` Out of Scope: 'Adding any new logger names (e.g. `koan.steering.trace`). User confirmed: DEBUG level on existing loggers is sufficient.' The user had picked the 'DEBUG -- silent by default' option over the 'Dedicated logger' option at intake.

Despite this, the plan wrote a directive in `plan.md` instructing the executor to add `from ..logger import get_logger` and `log = get_logger('steering')` to `koan/agents/steering.py`, with the rationale 'the file currently has no logger'. The plan introduced exactly what the brief's Out of Scope had excluded. Root cause: the producer rationalized the new logger as a pragmatic file-scope addition rather than recognizing that any new `koan.steering*` namespace logger fell under the user's rejected dedicated-logger option.

Adversarial review caught the violation by walking brief.md's Out of Scope section line by line and matching each plan directive against each Out of Scope item; the fix relocated the secondary observability into the existing steering callers and reduced the steering.py directive to a docstring-only update, after which the plan executed cleanly.

Lesson: brief.md Out of Scope is a higher-precedence enforcement tool than docstring discipline or approach soundness; review walks it line by line and matches each plan directive against each Out of Scope item. A plan rationalizing why an Out of Scope item should not apply to a specific case is itself the violation -- the brief is frozen and is the authority. This check belongs to plan review, now the mechanical fresh-context reviewer spawned on `plan.md` write, whose findings the plan producer reconciles inline before advancing.

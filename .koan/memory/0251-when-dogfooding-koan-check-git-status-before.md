---
title: When dogfooding koan, check git status before spawning an executor because
  the tree may hold a prior run's uncommitted refactor
type: procedure
created: '2026-06-24T03:42:09Z'
modified: '2026-06-24T03:42:09Z'
related:
- 0012-koan-is-dog-fooded-on-its-own-development-meta.md
---

koan is developed by running koan on its own repository (dogfooding), so the koan working tree can already hold large uncommitted changes from a previous workflow run before a new run spawns its executor. During a 2026-06-24 plan run that fixed the edit_type='append' crash, the tree already contained a large uncommitted refactor that predated the run -- the living-documents change implemented on 2026-06-23, including its newly written memory entries. The executor correctly modified only its planned files, but those pre-existing changes could not be separated from the executor's diff by `git status` alone; file modification times were needed to attribute the planned files to the executor's run. The rule: when orchestrating a koan-on-koan run, inspect `git status` before spawning the executor, so the baseline is known and the executor's diff can be attributed and committed independently of unrelated in-flight work. Skipping this risks conflating the run's change with pre-existing work at commit time.

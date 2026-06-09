---
title: Eval runner must spawn koan as a subprocess; in-process create_app() causes
  fixture/current-tree version mismatch
type: lesson
created: '2026-04-23T16:53:59Z'
modified: '2026-04-27T14:13:12Z'
related:
- 0049-eval-solver-answers-all-koan-interactive-gates.md
- 0076-eval-fixture-snapshots-are-self-referential-git.md
---

This lesson was distilled on 2026-04-23 during the DeepEval migration after Leon observed intermittent phase-transition failures in eval runs that read like state corruption but were a version-mismatch artifact.

Context. The previous runner design (2026-04-19) flipped `app_state.yolo = True` on an in-process `AppState` handle and called `create_app()` from the same Python process that drove the eval. The orchestrator CLI (`claude` / `codex`) was spawned into that same process's file system view, with the fixture git submodule checked out at a pinned SHA as the target repo.

Failure mode. When the eval process imports koan modules at current-tree SHA and the spawned orchestrator CLI reads source files from the fixture snapshot SHA, the two views of koan disagree. Phase-routing tables, MCP tool handlers, and `koan_complete_step` step-guidance strings can differ across the two SHAs. Concretely, phase transitions broke when the server held one phase graph and the orchestrator's step-1 guidance expected a different one. The failure surfaces as a phase-transition ValueError or as orchestrator tool calls against endpoints that do not exist on the other side.

Fix adopted on 2026-04-23. Leon reworked the eval runner (`evals/runner.py`) to spawn koan as a subprocess via `python -m koan run --yolo --directed-phases ...` with the fixture submodule as working directory, so both the koan server and the orchestrator CLI read source from the same SHA. The eval harness interacts only via the subprocess's HTTP surface and exit code; no in-process `AppState` or `create_app()` is used.

Lesson for future eval-harness work in koan: any component that is versioned alongside koan's source must be exercised from a single Python import root per run. When the fixture SHA and the harness SHA differ (which they usually do in benchmark work), the only safe boundary is a subprocess. In-process create_app() reuse is a trap whenever fixtures pin old SHAs of the same codebase.

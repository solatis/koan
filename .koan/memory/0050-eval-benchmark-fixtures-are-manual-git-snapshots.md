---
title: Eval benchmark fixtures are manual git snapshots of koan at specific commits
type: decision
created: '2026-04-17T12:06:26Z'
modified: '2026-04-17T12:06:26Z'
---

The koan eval benchmark fixture format was established on 2026-04-17 during the test suite overhaul planning session. Leon decided that the reference benchmark corpus would be the koan project itself, captured manually at specific git commits. Each fixture directory under `evals/fixtures/` contains three artifacts: `task.md` (the task description as UTF-8 plain text), `snapshot.tar.gz` (a `git archive HEAD --format=tar.gz` of the target project at a specific commit), and `memory/` (a copy of `.koan/memory/` at that commit). Leon's rationale: using koan itself as the reference corpus captures real-world complexity; re-capture is simple (take a new snapshot at a new commit). Leon rejected two alternatives: fully synthetic task descriptions against a fictional codebase (risk: synthetic inputs may not expose real failure modes) and live session capture from actual koan runs (concern: fragile and labor-intensive to re-capture).

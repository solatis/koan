---
title: 'Artifact design doctrine: distinct lifetimes, reader-driven contents, lifetime
  taxonomy'
type: decision
created: '2026-04-24T09:30:00Z'
modified: '2026-04-24T09:30:00Z'
related:
- 0015-three-active-workflows-plan-milestones-stub.md
- 0087-phasecontext-resets-on-koansetphase-orchestrator.md
- 0088-phase-module-create-or-update-pattern-check.md
---

The koan workflow run directory (`~/.koan/runs/<id>/`) accumulates phase-produced artifacts (`brief.md`, `milestones.md`, `plan.md` or `plan-m{N}.md`) that cross phase boundaries. On 2026-04-24, Leon (collaborating with an external Claude Desktop session) drafted and endorsed an artifact-design doctrine for koan built on three principles. First: each artifact has exactly ONE lifetime -- mixing content from different lifetimes inside one file multiplies rewrite risk. Second: each artifact serves specific downstream readers, and content no downstream phase actually needs is clutter; content that must cross phase boundaries is exactly what files are for (conversation history is unreliable for that purpose). Third: work backwards from reader needs to writer obligations -- a phase's job is defined by what its output must contain. The lifetime taxonomy has three classes: **frozen** (`brief.md` -- written once, not re-written), **additive-forward** (`milestones.md` -- rewritten across the run but Outcome sections are append-only, history stays visible), and **disposable** (`plan-m{N}.md` / `plan.md` -- written once, consumed once, then compressed into the milestone's Outcome). The doctrine was captured as `docs/artifacts.md` in the same curation run.

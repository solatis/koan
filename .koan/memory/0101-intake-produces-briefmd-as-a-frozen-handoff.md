---
title: Intake produces brief.md as a frozen handoff artifact
type: decision
created: '2026-04-24T09:30:09Z'
modified: '2026-06-20T03:38:30Z'
---

Intake (`koan/phases/intake.py`) writes `brief.md` to the run directory as its handoff artifact to every downstream phase -- core-flows and tech-plan in the initiative workflow, plus milestone, plan, execute, and curation. Leon endorsed this over intake producing only an ephemeral chat summary. The brief has seven sections: (1) **Initiative** -- one paragraph restating the user's task in intake's refined wording; (2) **Scope** -- in-scope and out-of-scope bullets, where out-of-scope matters more because it prevents downstream scope growth; (3) **Affected subsystems** -- concrete paths/modules with one-line descriptions, grounding downstream decomposition in real code; (4) **Decisions** -- numbered, each with rationale and rejected alternatives, each a constraint downstream plans must respect; (5) **Constraints** -- cross-cutting technical/architectural/operational; (6) **Assumptions** -- stated explicitly so they are falsifiable if execution reveals them wrong; (7) **Open questions** -- caution zones for downstream phases. Lifecycle rule: `brief.md` is **frozen** after intake. If execution reveals an assumption is wrong or scope must shift, that is recorded in the current milestone's Outcome section (light path) or handled by re-running intake (heavy path); silent amendment of `brief.md` is prohibited because downstream phases rely on its stability.

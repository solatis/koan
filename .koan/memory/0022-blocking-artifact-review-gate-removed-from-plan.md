---
title: Blocking artifact review gate removed from plan workflow; chat-based phase
  transitions replace it
type: decision
created: '2026-04-16T09:02:51Z'
modified: '2026-04-16T09:02:51Z'
related:
- 0015-three-active-workflows-plan-milestones-stub.md
- 0016-steering-vs-phase-boundary-message-routing-dual.md
---

The koan plan workflow in `koan/lib/workflows.py` includes four phases: intake, plan-spec, plan-review, and execute. On 2026-04-03, the workflow redesign plan (`plans/2026-04-03-workflow-types-and-plan-mode.md`) documented the removal of the blocking `koan_review_artifact` tool and the `POST /api/artifact-review` backend route. The maintainer recorded the rationale (Decision D1): artifact review and "what do I do next?" should be one conversation, not two sequential blocking gates. Under the removed design, the orchestrator wrote an artifact, then a blocking modal required Accept/Reject before phase transition suggestions appeared -- two sequential pauses for what is conceptually one moment: "here's what I did -- what should we do next?" The replacement pattern was established as: the orchestrator writes an artifact, gives a progress update in chat via `koan_yield`, and presents suggested next phases. The user reviews the artifact in the artifacts panel and responds conversationally. The maintainer noted this aligned with Traycer's design (the reverse-engineered origin system), which had no blocking modal -- artifacts appeared in a sidebar and the "what's next?" conversation implicitly covered feedback.

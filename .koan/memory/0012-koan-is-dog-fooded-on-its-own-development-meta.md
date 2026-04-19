---
title: Koan is dog-fooded on its own development -- meta-context for agents
type: context
created: '2026-04-16T08:34:35Z'
modified: '2026-04-16T08:34:35Z'
---

Koan is a solo project maintained by Leon Mergen, as confirmed by Leon in a curation run on 2026-04-16. Since the initial koan design on 2026-02-10, Leon adopted a practice of using koan's own plan workflow to develop koan itself -- dog-fooding the system as its own first user. This creates a meta-context constraint for any agent working on the koan codebase: workflow instructions and phase prompts in `koan/phases/*.py` and `koan/lib/workflows.py` are runtime instructions for koan's orchestrator subagents to execute, not instructions for the agent currently editing the source files. For example, the `SYSTEM_PROMPT` strings in `koan/phases/intake.py` are the intake orchestrator's role instructions; `koan/phases/curation.py` contains the step guidance that koan's curation orchestrator follows. An agent must not conflate "a prompt being analyzed as source material" with "a prompt being given as a direct instruction." Leon named this the "meta use of koan" and stated it explicitly in the task prompt for the 2026-04-16 curation run.

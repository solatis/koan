---
title: 'Role-curated tool vocabularies enforced by ToolPolicy + compose_toolset: withhold
  tools that do not belong to a role'
type: procedure
created: '2026-04-18T14:36:10Z'
modified: '2026-06-04T14:26:26Z'
related:
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0066-synthesis-expensive-memory-tools-scoped-to.md
---

koan curates each agent role's tool vocabulary: a role (orchestrator, scout, executor) is given only the tools that match its job, and tools that have nothing to do with the role are withheld to reduce the chance the agent misbehaves by reaching for them. Synthesis-heavy tools such as `koan_reflect` stay orchestrator-only even though they are read-only -- an executor wandering into synthesizing project history while it is supposed to be implementing is exactly the off-task behavior the curation prevents. On the agent path this curation is enforced by construction: `koan/tools/tool_policy.py` holds the allowlist data as a `ToolPolicy` (per-role tool sets, a universal set of cheap memory and artifact-read tools allowed to every role, and phase-gated sets such as bash, `koan_request_scouts`, `koan_request_executor`, and the story tools), and `compose_toolset(policy, role, phase)` builds the exact toolset registered for an agent so a withheld tool is never offered to the model. When adding a tool, decide its scope: a tool every role needs goes in the universal set; otherwise it goes in the owning role's set, and a phase-conditional tool goes in the relevant phase set. The rejected alternative -- making every read tool universal by default -- would hand roles tools they have no business calling.

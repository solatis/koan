---
title: Orchestrator tool vocabulary is composed per role (static, full) with phase-appropriateness
  enforced by a call-time recoverable gate
type: decision
created: '2026-06-04T14:14:07Z'
modified: '2026-06-23T02:23:14Z'
related:
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
- 0026-recoverable-vs-unrecoverable-error-classification.md
- 0009-permission-fence-impractical-across-llm-backends.md
- 0243-koan-execution-unbundled-into-koanrequestexecutor.md
---

koan composes an agent's registered tool vocabulary per ROLE -- compose_toolset(policy, role) in koan/tools/tool_policy.py -- producing a static, full tool set that stays byte-stable across every phase. For the long-lived in-process orchestrator this is load-bearing: its toolset and instructions are built once at run() start and reused for the whole workflow, so a phase change that altered the registered vocabulary would invalidate the prompt-cache prefix. The general cross-backend check_permission gate (koan/lib/permissions.py) stays removed and the allowlist DATA survives as the ToolPolicy dataclass. Phase-appropriateness for the orchestrator's three phase-conditional tools (koan_request_executor, bash, koan_request_scouts) is no longer done by construction-time per-phase composition; it is enforced at CALL TIME by phase_gate_message, which returns a recoverable error (the _permission_error_result envelope for the koan-tool cores, or an 'Error: ...' string for bash) when one of these tools is invoked in a phase outside its allowed set (_ORCHESTRATOR_*_PHASES). The model sees these tools and learns recoverably when they are usable. Leon chose this over two alternatives: per-phase toolset recomposition, rejected because changing the tool-definition block at a phase boundary forces a prompt-cache miss; and reviving the cross-backend runtime fence, rejected because the call-time gate is a narrow in-process per-tool check rather than that fence. The earlier per-(role, phase) construction-time design, combined with the once-per-run toolset build, silently froze the orchestrator's vocabulary at the workflow's initial phase, which is the failure that motivated moving phase-appropriateness to the call-time gate.

---
title: Plan built on the PydanticAI v2 beta assumed its API from a wheel analysis;
  pin pre-releases and verify symbols against the installed package
type: lesson
created: '2026-06-04T14:19:53Z'
modified: '2026-06-04T14:19:53Z'
related:
- 0143-koan-project-dependency-pin-policy-exact-pins.md
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
---

koan's agent-layer plan specified `pydantic-ai-slim==2.0.0b5` and described its capabilities API from a wheel-extraction analysis rather than from an installed package, and several of those assumptions were wrong. `2.0.0b5` is a pre-release that pip installs only with `--pre`, so an ordinary install silently resolved the environment to stable `1.86.0` instead; the two lines diverge on the history-processor capability (`1.x` exposes `HistoryProcessor`, the beta exposes `ProcessHistory`), and the mismatch broke agent construction outright. Root cause: building a plan on a dependency that was never installed, and trusting a wheel analysis over the symbols the installed package actually exports. Prevention: pin pre-releases deliberately (`--pre`, and lock the version) and verify every symbol the plan depends on against the installed package before designing on top of it; a spike that installs and probes the dependency is the validation, not the wheel read. The `1.x` API turned out closer to reality than the analyzed beta.

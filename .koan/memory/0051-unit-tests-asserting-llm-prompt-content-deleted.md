---
title: Unit tests asserting LLM prompt content deleted; pure-logic tests retained
type: decision
created: '2026-04-17T12:14:23Z'
modified: '2026-04-17T12:14:23Z'
---

The koan test suite retention policy was established on 2026-04-17 during the test suite overhaul planning session. Leon stated that tests asserting on LLM prompt content (hardcoded strings in step guidance text, workflow dataclass structure, phase shape) are low-value because they break whenever prompt engineering changes and provide no signal about actual LLM behavior. Leon decided to delete the following test files entirely: `tests/test_phases.py` (286 lines of step-progression and prompt-text content tests), `tests/test_workflows.py` (288 lines of workflow dataclass structure tests), `tests/phases/test_curation.py` (phase shape and SYSTEM_PROMPT content checks), and `tests/test_driver.py` (17-line import smoke test). Leon decided to retain tests that cover deterministic pure-logic algorithms: `tests/test_permissions.py` (permission gate logic), `tests/test_projections.py` (projection fold), `tests/test_audit_fold.py` (audit fold), `tests/test_runners.py` (stream event parsing), `tests/test_probe.py` (runner probing), `tests/test_mcp_check_or_raise.py` (permission check), `tests/test_interactions.py` (interaction queue FIFO logic), `tests/test_subagent.py`, and all twelve files under `tests/memory/`.

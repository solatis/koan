---
title: Redirecting koan's agent spawn to RunState.frozen_config left a skipif-gated
  live Gemini test on the old path -- green in keyless CI, broken with a key present
type: lesson
created: '2026-06-10T09:52:45Z'
modified: '2026-06-10T09:52:45Z'
related:
- 0115-plan-spec-analysis-must-inventory-non-source.md
- 0196-koan-freezes-a-runs-resolved.md
---

koan's agent spawn path was changed so credential and model resolution read `app_state.run.frozen_config` / `app_state.run.frozen_credential_store` (the per-run denormalized snapshot) instead of `app_state.provider_config.config` / `credential_store`. The executor migrated the start-run and subagent tests (`tests/test_web_flows.py`, `tests/test_subagent.py`) to seed the new `RunState.frozen_*` fields, but missed `tests/test_pydantic_ai_agent.py::test_live_gemini_intake_turn_advances_step`, which still set only the old `provider_config` path. That test is gated by `@pytest.mark.skipif` on `GOOGLE_API_KEY` / `GEMINI_API_KEY`, so it is skipped in any keyless environment and the default suite reported all-green; it failed (`AgentError: No stored credential for provider 'google'`) only where a real key was present, because with `frozen_config` unset the spawn path resolved no credential.

Root cause: a runtime read was redirected to a new source, but not every test that seeded the old source was updated -- and the missed one is a key-gated live test that does not execute in the standard keyless run, so it is invisible to a green-suite check. The prevention rule: when redirecting a runtime config or credential read from one source to another, grep the test tree for every setup that writes the OLD source (here `app_state.provider_config.config` / `.credential_store`) and migrate all of them, explicitly including `skipif`-gated live tests the default suite skips.

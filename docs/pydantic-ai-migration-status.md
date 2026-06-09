# PydanticAI Migration -- Status & Remaining Plan

> **Migration complete (2026-06-05).** All milestones (M1-M7) landed on
> `migrate/pydantic-ai`. The in-process PydanticAI loop, end-of-turn control
> loop (`resolve_turn_outcome`), `koan_suggest_next`, provider-credential
> settings, usage gauges (cost / context-window-% / cache), and documentation
> sweep are all done. Suite: green. `tsc --noEmit`: clean.



**Branch:** `migrate/pydantic-ai` (9 commits on top of `master`)
**Source run:** `~/.koan/runs/1780450413-662fc093` (initiative workflow)
**Last updated:** 2026-06-04

## What this migration is

Move koan's agent layer off the Claude Agent SDK / codex+gemini CLIs onto native
PydanticAI (`pydantic-ai-slim==2.0.0b5`), with koan owning the ReAct loop
in-process. `koan_yield` is gone (the loop's terminal-text turn is the
hand-back); koan tools + subagents run in-process; built-in tools are
reimplemented; all four providers (google/anthropic/openai/bedrock) are
targeted. Hard cutover -- the old path is deleted at the end. `main` is accepted
non-shippable between M2 and M9.

## Current state: M1 through M7.5 DONE, green

Suite: **800 passed, 1 skipped, 67 xfailed, 0 failed.** `tsc --noEmit`: clean.
On the pydantic path koan does multi-turn orchestration, in-process subagents,
all four providers, web tools, and the restored hand-back UX (YieldPanel
suggestions + attachment audit).

| Commit    | Milestone                                                                                                                  |
| --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `d034fbb` | Pre-flight + **M5b**: build repair, restored `2.0.0b5` pin (venv had drifted to 1.86.0), `koan_yield` removal cascade      |
| `40cb324` | **M5c**: wired `run()` -> `run_agent_loop` (was dead code; orchestrator couldn't do multi-turn) + `test_loop.py`           |
| `a1f73e7` | **M6**: in-process subagent spawning (scouts/executor tools, `_active_tasks` registry, crash containment, shutdown cancel) |
| `17c3dec` | **M7 pt1**: provider fan-out (anthropic/openai/bedrock) + caching in `adapter.py`                                          |
| `b9743e0` | **M7 pt2**: `web_search`/`web_fetch` (local ddgs+httpx) + header token gauge (`UsageGauge`)                                |
| `794ab30` | **M7.5**: restored YieldPanel suggestions (`build_phase_suggestions`) + `tool_attachments` audit on resume                 |
| `82e69e9` | **M9 step 1**: relocated `StreamEvent` + `KOAN_MCP_TOOLS` to `koan/agents/events.py` (re-exported from `runners/base.py`)  |

> **All 9 commits are UNSIGNED** -- the 1Password SSH signer (`op-ssh-sign`)
> stopped responding early in the session. Re-sign with
> `git rebase --exec 'git commit --amend --no-edit -S' master` after unlocking,
> or amend individually.

### Key findings during execution (corrections to `milestones.md`)

- **Two build blockers, not one.** Besides the known `IndentationError`, the
  venv had drifted off the pinned `2.0.0b5` onto stable `1.86.0`, whose
  capabilities API (`HistoryProcessor` vs the beta's `ProcessHistory`) broke
  agent construction. `2.0.0b5` is a pre-release (install with `--pre`); a
  cached wheel is in `~/.cache/uv`. uv.lock already pins it.
- **M5a was never actually finished.** `run_agent_loop` existed but was never
  called -- `run()` was still the M2 single-turn path, so the orchestrator ran
  one turn and exited. Fixed in M5c.

### Known deferred items (intentional, documented)

- **Cost / context-window / cache gauges** (M7): only the token gauge shipped.
  Cost needs a koan-model -> genai-prices-catalog mapping that can't be
  validated without live provider calls; deferred to the frontend pass.
- **Binary/image attachment delivery to multimodal models** (M7.5): resume
  attachments are text-only; audit visibility is restored but content delivery
  needs a multimodal `agent.iter` prompt + live verification.
- **Agent-protocol slim** (`register_process`/`exit_code`/`stderr_output`):
  deferred from M6 to M9 (folded into the rip-out below).

## Remaining: M8 (settings) + M9 (rip-out) -- combined, entangled

M8 and M9 both delete `probe.py` / the installation concept / the
`ProfileTier.runner_type` reads that break app startup (the cause of the 67
xfails + the `conftest.py` `client`-fixture xfail hook). Do them as one pass.

### Deletion dependency graph (mapped this session)

Modules to delete and what blocks each (relocate/rework importers FIRST):

- **`koan/runners/base.py`** -- DONE relocating its survivors (step 1). Now only
  holds the `Runner` protocol; deletes with the CLI runners.
- **`koan/agents/claude.py`, `koan/agents/command_line.py`,
  `koan/runners/{codex,gemini}.py`** -- imported by `subagent.py`,
  `agents/registry.py`, `agents/__init__.py`, `runners/__init__.py`, and tests
  `test_runners.py`, `test_probe.py`, `test_subagent.py`. Requires the protocol
  slim first (so `subagent.py` stops reading `agent_impl.exit_code/stderr_output`
  and calling `register_process`). `test_runners.py` is deleted.
- **`koan/web/mcp_endpoint.py`** (+ `/mcp` route + `AgentResolutionMiddleware` in
  `app.py`) -- 13 importers. `koan/tools/koan_tools.py` imports
  `_render_curation_payload` FROM it (relocate that helper into `koan_tools.py`
  or `web/uploads.py` first). Test files that test the MCP handlers directly
  must be rewritten to call the in-process cores or deleted:
  `test_mcp_memory.py`, `test_mcp_search.py`, `test_mcp_reflect.py`,
  `test_mcp_check_or_raise.py`, `test_attachments_delivery.py` (scenarios 3/4),
  `test_phase_guidance.py` (the `build_mcp_server` bits).
- **`koan/lib/permissions.py`** -- `koan/tools/tool_policy.py` reads its tables;
  inline them into `tool_policy.py` first. `test_tool_policy.py` cross-checks
  `compose_toolset` against `check_permission` -- drop that half of the test.
- **`koan/probe.py`** -- imported by `app.py` settings endpoints +
  `ClaudeSDKAgent.list_models`. Delete after the settings rework + claude.py.
  Tests `test_probe.py` deleted.

### Protocol slim (do first in the rip-out)

`koan/agents/base.py`: drop `register_process`, `exit_code`, `stderr_output`.
Rework `koan/subagent.py` to derive the result without them: catch `AgentError`
(failure) vs clean completion (success) -> `exit_code` 0/1; the failure message
comes from the caught `AgentError`, not `agent_impl.stderr_output`. Drop the
`register_process` call + `AppState._active_processes` (now unused). Update the
`FakeAgent*` doubles in `tests/test_subagent.py` to signal failure by raising
`AgentError` in `run()` instead of returning a non-zero `exit_code` property.

### Settings rework (M8)

`koan/web/app.py`: `_validate_profile_tiers` and `/api/settings/{body,
profile-form,installation-form}` + `/api/probe` read `tier.runner_type` /
`inst.runner_type` / probe results. Rework onto `provider_auth` +
`ModelSpec{provider,model}`; replace binary detection with credential entry +
validation (validate by constructing the provider model via the M7 adapter).
Refresh `compute_builtin_profiles` (`agents/registry.py`). Then delete the
`conftest.py` xfail hook and make `test_web_flows.py` + `test_uploads.py` pass.

Frontend `SettingsOverlay.tsx` (607 lines, legacy `components.css`/`layout.css`):
replace `InstallationForm`'s binary-path + detect flow with provider credential
entry; source `ProfileForm` options from the provider/model registry. Respect
the protected design system; `tsc --noEmit`. **Visual review recommended.**

### Dependencies + final verification

- `pyproject.toml`: drop `claude-agent-sdk` and `fastmcp`; `uv lock`.
- Remove dead `mcp_url` plumbing (`subagent.py`, `AgentOptions`) and
  `CLAUDE_TOOL_WHITELISTS` / `_build_claude_tool_lists`.
- Retire the 67 xfail markers whose subjects are deleted.
- Final: `import koan` clean without sdk/fastmcp; full suite green; live Gemini
  run via the app (intake -> scouts -> executor) with no `/mcp` traffic.

## Verification commands

- `.env/bin/python -m pytest -q`
- `cd frontend && npx tsc --noEmit`
- Live Gemini single-agent smoke runs in `test_pydantic_ai_agent.py` when
  `GOOGLE_API_KEY` is set (it is, in this environment).

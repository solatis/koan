# Plan: make koan usable on the PydanticAI path (Gemini, env-configured)

**Goal (user-set):** a working koan I can actually run -- the web app boots,
provider config comes from env vars + `~/.koan/config.json` (no TOML), and a
real workflow runs end-to-end on **Gemini** (live-verified). The M9 rip-out +
full settings-UI rework follow as a hardening pass AFTER koan is usable.

**Branch:** `migrate/pydantic-ai` (continues the 10-commit migration).

## Root cause of "can't use koan"

The web app crashes on boot: `koan/web/app.py:1150` `_serialize_profile` reads
`pt.runner_type`, but M1 reshaped `ProfileTier` to `{model: ModelSpec}`
(`ModelSpec{provider, model, thinking, settings, caching}`). The lifespan
startup (`_push_initial_config_events`) throws `AttributeError` -> server never
comes up. Secondary: the settings/probe layer is built on CLI-binary detection
(`probe_all_runners`, `agent_installations`, `runner_type`), which is obsolete
on the pydantic path -- provider availability must come from env credentials.

## Phase A -- boot + run on Gemini (the usable milestone)

A1. **Fix config serialization** (`koan/web/app.py`):
- `_serialize_profile`: emit the new tier shape from `pt.model` (a ModelSpec):
  `{provider, model, thinking, caching, contextWindow}` instead of
  `{runner_type, model, thinking}`.
- Audit every other `tier.runner_type` / `pt.runner_type` / `inst.runner_type`
  read (`_validate_profile_tiers` ~117, `_push_initial_config_events` ~1267,
  the settings endpoints) and move them onto the ModelSpec/provider shape.

A2. **Provider availability from credentials, not CLI probe**:
- Replace the `probe_all_runners()` call in `_refresh_probe_state` with a
  credential probe: a provider is "available" when its env keys resolve
  (reuse `adapter.resolve_credentials` / a thin `provider_available(provider)`).
  Gemini -> available iff `GOOGLE_API_KEY`/`GEMINI_API_KEY` set.
- Drop the CLI installation auto-create block (codex/gemini `--yolo` args,
  `agent_installations` mutation) -- it has no meaning on the pydantic path.
- Keep `compute_builtin_profiles` returning the static Gemini ModelSpec
  profiles (already does; the `probe_results` arg is vestigial).

A3. **Start-run gating**: wherever the UI/endpoint enables "Start" only when
"runners are available", switch the check to "at least one provider's
credentials resolve" (Gemini via `GOOGLE_API_KEY`).

A4. **Settings endpoints** (`/api/settings/body`, `/api/probe`, the form
endpoints): return the new provider/profile shape without crashing. Minimal
viable: report configured providers + credential-resolution status + the
built-in Gemini profiles. (Full credential-entry UX is Phase C.)

A5. **Un-break the suite**: remove the `conftest.py` M8 xfail hook and make
`test_web_flows.py` + `test_uploads.py` pass against the new shapes (update the
assertions that expect `runner_type`/installations/probe).

A6. **LIVE VERIFY**: boot the app (background), POST a small `plan`-workflow
start-run with the Gemini profile, drive one intake turn via `/api/chat`, and
confirm from `koan.log` + the projection SSE that the orchestrator ran on
Gemini, handed back (terminal-text), and no `/mcp` traffic occurred. This is
the gate for "usable".

## Phase B -- M9 rip-out (hardening, after usable)

Per the deletion dependency graph in `pydantic-ai-migration-status.md`:
protocol slim -> delete legacy agents + CLI runners -> relocate
`_render_curation_payload` + delete `mcp_endpoint.py`/`/mcp` route -> inline
permission tables + delete `permissions.py` -> delete `probe.py` -> drop
`claude-agent-sdk`/`fastmcp` deps -> retire dead xfails + `mcp_url`/whitelist
plumbing. Each a green sub-commit; rewrite/delete the MCP/probe/runner test
suites as their targets go.

## Phase C -- settings UI + cost gauge (frontend, reviewable)

`SettingsOverlay.tsx` credential entry (replaces binary-path/detect); the
cost/context-window/cache gauges (needs the koan-model -> genai-prices mapping).
Frontend, visually reviewed by the user.

## Verification commands

- `.env/bin/python -m pytest -q`  (target: 0 failed, xfails shrinking)
- boot: `.env/bin/python -m koan ...` (or the app entrypoint) on a spare port
- live Gemini run driven via the HTTP API; check `~/.koan/runs/<id>/koan.log`

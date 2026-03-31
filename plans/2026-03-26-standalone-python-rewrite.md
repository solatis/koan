# Standalone Python Rewrite

**Status: Completed (2026-03-27)**

The HTTP MCP architecture (driver-hosted single endpoint at
`/mcp?agent_id={id}`) was adopted as described in this plan, replacing the
original per-subagent stdio MCP server design that was the open question at
plan-writing time. `ipc.json` file-polling was fully eliminated in favor of
`asyncio.Future`-based blocking tool calls. The TypeScript codebase has been
deleted.

---

Rewrite Koan as a standalone Python orchestrator. A single HTTP server hosts
both the web dashboard and MCP tool endpoints. Children connect to the
driver's MCP endpoint at `http://localhost:{port}/mcp?agent_id={id}` -- the
driver handles all tool calls in-process, no separate MCP server processes.
CLI agents (`claude`, `codex`, `gemini`) are interchangeable child runtimes
behind an abstract runner interface.

This is a **big-bang rewrite** -- no backwards compatibility with the TypeScript
codebase. The TS code is frozen and deleted after Python reaches parity.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                     Python Orchestrator                         │
│                      (single process)                          │
│                                                                │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  Driver   │  │   Starlette App  │  │  Phase Definitions   │  │
│  │  (FSM)    │  │                  │  │  (step guidance,     │  │
│  │          │  │  /mcp?agent_id=  │  │   system prompts)    │  │
│  │          │  │  /dashboard      │  │                      │  │
│  │          │  │  /events (SSE)   │  │                      │  │
│  └────┬─────┘  └────────┬─────────┘  └──────────┬───────────┘  │
│       │                 │                        │              │
│  ┌────┴─────────────────┴────────────────────────┴───────────┐  │
│  │                   Agent Registry                           │  │
│  │  agent_id → { role, step_engine, permissions, event_log }  │  │
│  └──┬──────────────┬──────────────┬──────────────────────────┘  │
│     │              │              │                              │
└─────┼──────────────┼──────────────┼──────────────────────────────┘
      │http          │http          │http
  ┌───┴────┐   ┌─────┴─────┐  ┌────┴─────┐
  │claude  │   │codex exec │  │gemini -p │
  │  -p    │   │           │  │          │
  └────────┘   └───────────┘  └──────────┘
```

**Single HTTP server, multiplexed by agent_id:** The driver runs one
Starlette app that serves both the web dashboard and MCP tool endpoints. Each
subagent connects to `http://localhost:{port}/mcp?agent_id={id}`. When a tool
call arrives, the server looks up the agent's state (role, step counter,
permissions) by `agent_id` in an in-process registry and handles the call
directly. No separate MCP server processes, no file-based IPC polling.

**In-process tool handling:** Tool calls that previously required file-based
IPC (`koan_ask_question`, `koan_request_scouts`, `koan_review_artifact`) are
now handled in-process. The HTTP request blocks until the driver has a
response — for `koan_ask_question`, the driver routes to the web UI, awaits
user input, and returns the answer as the MCP tool response. For
`koan_request_scouts`, the driver spawns scouts directly, awaits them, and
returns findings. No `ipc.json` intermediary.

**Agent-agnostic runner:** An abstract `Runner` interface handles child
process lifecycle. Three implementations from day one: `ClaudeRunner`,
`CodexRunner`, and `GeminiRunner`. Each knows how to inject per-process MCP
config pointing at the driver's HTTP endpoint, construct launch arguments,
and parse stdout for streaming events.

---

## Decisions

### Single HTTP server, not per-subagent MCP processes

Previous iterations of this plan used per-subagent stdio MCP server processes.
This added N processes, required file-based IPC polling between the MCP
server and the parent, and forced each MCP server to independently manage
audit state.

The HTTP approach collapses everything into one process:

- The driver, web dashboard, and MCP endpoint share a single Starlette app
- Tool calls arrive as HTTP requests with `agent_id` in the URL
- The agent registry (an in-process dict) maps `agent_id` → step engine,
  permissions, event log
- `koan_ask_question` routes directly to the web UI's pending-input mechanism
  (no file polling)
- `koan_request_scouts` spawns scouts in-process and awaits completion
  (no `ipc.json` intermediary)

The `agent_id` is assigned by the driver when spawning a subagent and passed
to the child via the MCP config URL. The MCP protocol's HTTP transport
(Streamable HTTP) carries the `agent_id` as a query parameter — no
out-of-band identification needed.

### Positive-only prompt guidance for permissions

System prompts tell the LLM which tools to call (positive guidance). They do
**not** list tools to avoid — negative guidance is less effective. Hard
enforcement lives in the MCP endpoint: if the child calls a tool its role
doesn't have, the endpoint returns an error. This mirrors the current
`checkPermission()` pattern but moves it from the old TS extension hook to
the HTTP tool handler.

### HTMX + server-rendered web UI

The dashboard is part of the same Starlette app that serves MCP. HTMX for
reactivity, SSE for push updates. No JS build step, no node dependencies.
Server renders HTML fragments; HTMX swaps them on SSE events. Token streaming
uses SSE directly into an HTMX target.

### File contracts simplified

The directory-as-contract invariant is preserved but simplified:

- `task.json` — driver writes before spawn, driver reads at agent registration
- `state.json` — driver writes (audit projection), available for debugging
- `events.jsonl` — driver appends audit events

**Removed:** `ipc.json` is no longer needed. Tool calls that previously
required file-based IPC (`koan_ask_question`, `koan_request_scouts`,
`koan_review_artifact`) are now in-process HTTP request/response cycles. The
MCP tool handler blocks on the HTTP request until the driver has a response.

### Step guidance lives in Python phase modules

Each phase (intake, brief-writer, orchestrator, etc.) is a Python module that
defines step names, system prompts, and step guidance content. The MCP
endpoint calls `get_step_guidance(step)` when `koan_complete_step` is
invoked. This is equivalent to the current `BasePhase.getStepGuidance()` but
in Python.

---

## Package Structure

```
koan/
├── __init__.py
├── __main__.py              # CLI entry point
├── driver.py                # Deterministic pipeline FSM
├── subagent.py              # Subagent manager (spawn child, register agent)
├── agents.py                # Agent registry: agent_id → state (in-process dict)
├── step_engine.py           # Step state machine (one instance per agent)
├── permissions.py           # Role/step/path enforcement
├── tools/
│   ├── __init__.py          # Tool registration for MCP endpoint
│   ├── workflow.py          # koan_complete_step
│   ├── ask.py               # koan_ask_question (in-process → web UI)
│   ├── scouts.py            # koan_request_scouts (in-process spawn)
│   ├── review.py            # koan_review_artifact (in-process → web UI)
│   ├── orchestrator.py      # koan_select_story, etc.
│   └── workflow_decision.py # koan_propose_workflow, koan_set_next_phase
├── phases/
│   ├── __init__.py
│   ├── base.py              # Step guidance interface
│   ├── intake.py            # 5-step intake workflow
│   ├── brief_writer.py      # 3-step brief workflow
│   ├── scout.py
│   ├── decomposer.py
│   ├── orchestrator.py
│   ├── planner.py
│   ├── executor.py
│   └── workflow_orchestrator.py
├── runners/
│   ├── __init__.py
│   ├── base.py              # Abstract Runner interface
│   ├── claude.py            # ClaudeRunner
│   ├── codex.py             # CodexRunner
│   └── gemini.py            # GeminiRunner
├── epic/
│   ├── __init__.py
│   ├── state.py             # Epic/story state I/O (JSON)
│   ├── types.py             # EpicPhase, StoryStatus, etc.
│   └── artifacts.py         # Artifact listing/reading
├── audit/
│   ├── __init__.py
│   ├── events.py            # Event type definitions
│   ├── fold.py              # Pure projection fold
│   ├── log.py               # EventLog (append + state.json)
│   └── formatter.py         # LogLine formatters for web UI
├── web/
│   ├── __init__.py
│   ├── app.py               # Starlette app (dashboard + MCP endpoint)
│   ├── mcp.py               # /mcp?agent_id= endpoint (Streamable HTTP)
│   ├── sse.py               # /events SSE endpoint
│   ├── routes/              # Dashboard HTTP route handlers
│   ├── templates/           # Jinja2 + HTMX templates
│   └── static/              # CSS
├── config.py                # Model tiers, scout concurrency
├── lib/
│   ├── __init__.py
│   ├── phase_dag.py         # Phase transition DAG
│   └── time.py
└── types.py                 # Shared types
```

---

## Subagent Lifecycle

No separate MCP server processes. The driver's HTTP server handles everything.

```
Driver (Starlette app on :port)              Child Agent (claude/codex/gemini)
  │                                                │
  ├─ mkdir subagentDir                             │
  ├─ write task.json                               │
  ├─ assign agent_id                               │
  ├─ register agent in registry                    │
  │  (read task.json → init step engine,           │
  │   permissions, event log)                      │
  ├─ write MCP config → http://localhost:{port}/   │
  │   mcp?agent_id={agent_id}                      │
  ├─ spawn child ──────────────────────────────────►│
  │                                                ├─ connect to MCP endpoint
  │                                                │
  │◄────── POST /mcp koan_complete_step ───────────┤
  ├─ look up agent_id in registry                  │
  ├─ check permissions                             │
  ├─ advance step 0→1                              │
  ├─ return step 1 guidance ───────────────────────►│
  │                                                ├─ do work
  │◄────── POST /mcp koan_ask_question ────────────┤
  ├─ route to web UI (in-process)                  │
  ├─ await user input (SSE + POST /api/answer)     │
  ├─ return answer ────────────────────────────────►│
  │                                                ├─ continue work
  │◄────── POST /mcp koan_request_scouts ──────────┤
  ├─ spawn scout children directly                 │
  ├─ await all scouts (each is its own agent_id)   │
  ├─ return findings ──────────────────────────────►│
  │                                                ├─ continue work
  │◄────── POST /mcp koan_complete_step ───────────┤
  ├─ advance step 1→2 (or "Phase complete.")       │
  ├─ return guidance ──────────────────────────────►│
  │                                                │
  │                              child exits ◄─────┤
  ├─ deregister agent_id                           │
  ├─ route to next phase                           │
```

---

## MCP Tool Surface

Tools exposed at the `/mcp?agent_id={id}` endpoint. The driver looks up the
agent's state from the in-process registry on every call.

| Tool                    | Schema                                  | Driver behavior                                                                                 |
| ----------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `koan_complete_step`    | `{ thoughts?: string }`                 | Check permissions → advance step engine → return guidance or "Phase complete."                  |
| `koan_ask_question`     | `{ questions: [...] }`                  | Check permissions → push to web UI → await user response → return answer                        |
| `koan_request_scouts`   | `{ scouts: [...] }`                     | Check permissions → spawn scout children (each gets own agent_id) → await all → return findings |
| `koan_review_artifact`  | `{ path, description? }`                | Check permissions → read artifact → push to web UI → await feedback → return                    |
| `koan_select_story`     | `{ story_id }`                          | Validate status → write story state + status.md                                                 |
| `koan_complete_story`   | `{ story_id, summary? }`                | Validate status → write story state + status.md                                                 |
| `koan_retry_story`      | `{ story_id, failure_summary }`         | Validate status → write story state + status.md                                                 |
| `koan_skip_story`       | `{ story_id, reason }`                  | Validate status → write story state + status.md                                                 |
| `koan_propose_workflow` | `{ status_report, recommended_phases }` | Push to web UI → await user direction → return feedback                                         |
| `koan_set_next_phase`   | `{ phase, instructions? }`              | Validate against DAG → write `workflow-decision.json`                                           |

All tools pass through the permission fence before execution. The fence reads
role and current step from the agent's entry in the registry.

---

## Runner Interface

```python
class Runner(Protocol):
    """Abstract interface for spawning a child agent process."""

    def build_command(
        self,
        boot_prompt: str,
        mcp_url: str,         # e.g. "http://localhost:8420/mcp?agent_id=intake-abc123"
        model: str | None,
        cwd: str,
    ) -> list[str]:
        """Return the full command-line to spawn the child."""
        ...

    def write_mcp_config(self, mcp_url: str, config_dir: str) -> None:
        """Write agent-specific MCP config file pointing at the HTTP URL."""
        ...

    def parse_stream_event(self, line: str) -> StreamEvent | None:
        """Parse one stdout line into a normalized event, or None to skip."""
        ...

    @property
    def name(self) -> str: ...
```

All runners point the child at the same HTTP endpoint — only the config
injection mechanism differs per CLI.

**`ClaudeRunner`:** Writes JSON config to `{config_dir}/mcp-config.json`:
`{"koan":{"type":"http","url":"http://localhost:{port}/mcp?agent_id={id}"}}`
Spawns: `claude -p --output-format stream-json --verbose --include-partial-messages --mcp-config {path} --strict-mcp-config --dangerously-skip-permissions "{boot_prompt}"`

**`CodexRunner`:** Injects via `-c` runtime overrides (per-process, not persisted):
`codex exec --json --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers.koan.url="http://localhost:{port}/mcp?agent_id={id}"' "{boot_prompt}"`

**`GeminiRunner`:** Writes `.gemini/settings.json` into `cwd`:
`{"mcpServers":{"koan":{"type":"http","url":"http://localhost:{port}/mcp?agent_id={id}"}}}`
Spawns: `gemini -p --yolo --allowed-mcp-server-names koan -o stream-json "{boot_prompt}"` with `cwd=subagentDir`.

The runner does not handle tools, permissions, or state. It only handles
process lifecycle and stream parsing.

---

## Phase Modules

Each phase module exports:

```python
ROLE: str                         # e.g. "intake"
TOTAL_STEPS: int                  # e.g. 5
REVIEW_GATED_STEP: int | None     # step requiring artifact review acceptance

def system_prompt() -> str:
    """Role identity and rules. No task details."""

def step_name(step: int) -> str:
    """Human-readable step name."""

def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Step instructions. Task details delivered here, not in boot prompt."""

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Next step number, or None for phase complete. Pure function."""

def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Pre-condition check. Returns error string or None to allow."""
```

The driver's step engine (looked up by `agent_id`) calls these functions.
`PhaseContext` carries `epic_dir`, `subagent_dir`, `phase_instructions`, and
any phase-specific state (e.g., intake confidence level).

---

## Phases

### Phase 0 — HTTP MCP Endpoint + Step Engine

Build the Starlette app with the MCP endpoint and `koan_complete_step`.

**Deliverables:**

- `koan/web/app.py` — Starlette app with `/mcp?agent_id=` endpoint
- `koan/web/mcp.py` — MCP Streamable HTTP handler
- `koan/agents.py` — agent registry (in-process dict)
- `koan/step_engine.py` — step state machine
- `koan/permissions.py` — permission fence
- `koan/tools/workflow.py` — `koan_complete_step` handler
- `koan/phases/base.py` — phase interface
- `koan/phases/intake.py` — intake phase (port from TS)
- `koan/audit/` — event log, fold, projection

**Validation:** Start the Starlette app, register a test agent manually,
connect a `claude` session with MCP config pointing at the HTTP endpoint.
Verify the LLM calls `koan_complete_step`, receives step 1 guidance, does
work, calls again, and completes the phase.

### Phase 1 — In-Process Tools + Single-Phase Driver

Add remaining MCP tools (handled in-process) and the driver for intake.

**Deliverables:**

- `koan/tools/ask.py` — `koan_ask_question` (routes to web UI, awaits response)
- `koan/tools/scouts.py` — `koan_request_scouts` (spawns scouts directly)
- `koan/tools/review.py` — `koan_review_artifact` (routes to web UI)
- `koan/subagent.py` — spawn child, register agent, parse stdout
- `koan/runners/base.py` + `koan/runners/claude.py` — first runner
- `koan/driver.py` — minimal driver: run intake phase only
- Minimal web UI: question form + artifact review (HTMX)

**Validation:** Run `koan plan` from CLI. Intake phase completes: scouts
dispatch, questions asked via web UI, `landscape.md` produced.

### Phase 2 — Full Pipeline + Multi-Agent

Extend driver to all phases. Add Codex and Gemini runners.

**Deliverables:**

- All remaining phase modules (brief-writer through workflow-orchestrator)
- `koan/runners/codex.py` — Codex runner
- `koan/runners/gemini.py` — Gemini runner
- Full driver loop with story execution, retry, skip
- `koan/epic/state.py` — epic/story state I/O
- `koan/lib/phase_dag.py` — phase transition DAG
- Orchestrator tools (`koan_select_story`, etc.)
- Workflow decision tools (`koan_propose_workflow`, `koan_set_next_phase`)

**Validation:** Run full pipeline intake → brief → execution with
`claude`, `codex`, and `gemini` as child agents. Story loop completes
with retry/skip.

### Phase 3 — Web Dashboard

Rewrite the web UI in Python + HTMX.

**Deliverables:**

- `koan/web/app.py` — Starlette app
- `koan/web/sse.py` — SSE push endpoint
- HTMX templates for: activity feed, agent panels, question forms,
  artifact review, workflow decisions, model config, token streaming
- Port CSS from current UI

**Validation:** Dashboard displays real-time activity, handles all
interaction types, survives reconnects.

### Phase 4 — Polish + Delete TS

Harden, test, document. Delete the TypeScript codebase.

**Deliverables:**

- Test suite (unit + integration)
- CLI polish (`koan plan`, `koan config`)
- Documentation
- Delete `extensions/`, `src/`, `package.json`, TS config

---

## Invisible Knowledge

### Why a single HTTP MCP server, not per-subagent processes

Earlier iterations of this plan used per-subagent stdio MCP server processes.
This was architecturally clean (one process = one state machine) but introduced
unnecessary complexity:

- N extra processes for N subagents (lightweight, but still process management)
- File-based IPC polling between the MCP server and the driver for questions,
  scouts, and artifact review (`ipc.json` write → 300ms poll → response write)
- Each MCP server independently managed audit state, duplicating projection logic

The HTTP approach eliminates all of this. The driver's Starlette app serves
MCP at `/mcp?agent_id={id}`. The `agent_id` parameter in the URL solves the
routing problem: when `koan_complete_step` arrives, the driver looks up the
agent's state by ID in an in-process dict. No out-of-band identification, no
process coordination, no file polling.

Tools that need human interaction (`koan_ask_question`, `koan_review_artifact`)
route directly to the web UI's pending-input mechanism — the HTTP request blocks
until the user responds. Tools that spawn children (`koan_request_scouts`) do so
in-process. The entire tool lifecycle is a single HTTP request/response cycle.

### Why HTTP transport, not stdio

MCP supports both stdio (parent spawns server as subprocess) and HTTP
(Streamable HTTP, server listens on a port). We use HTTP because:

1. **Single server for all subagents.** With stdio, each subagent needs its
   own MCP server process. With HTTP, one server handles all agents via
   `agent_id` in the URL. Fewer processes, no per-subagent lifecycle.

2. **In-process tool handling.** The driver can handle `koan_ask_question`
   by routing directly to the web UI's pending-input mechanism. No file-based
   IPC polling. The HTTP request blocks until the user responds.

3. **The server is already running.** The web dashboard needs an HTTP server
   anyway. Adding `/mcp` to the same Starlette app is zero marginal cost.

4. **No server-ready timing.** The HTTP server starts before any subagent
   is spawned. Children connect to a server that's already listening.

All three CLIs support HTTP MCP servers:

- **Claude**: `--mcp-config` with `{"type":"http","url":"..."}`
- **Codex**: `-c 'mcp_servers.koan.url="..."'` runtime override
- **Gemini**: `.gemini/settings.json` with `{"type":"http","url":"..."}`

The runner's only job is writing the correct MCP config format for its CLI.

### Why positive-only prompt guidance for permissions

System prompts listing forbidden tools create a specific failure mode: the LLM reads
"do not call `koan_ask_question` during step 1" and the prohibition itself activates
the concept, making the mistake slightly more likely (the "don't think of an elephant"
problem). More practically, negative constraint lists grow stale as the permission
model evolves and are never comprehensive.

Positive guidance — "your tools for this step are X, Y, Z" — is a complete
specification. Combined with the MCP server's hard enforcement (unknown tool calls
return an error the LLM must handle), the prompt guides the LLM toward correct tool
selection while the server prevents incorrect tool execution regardless of what the
prompt says.

The architecture thus has two independent correctness layers: the prompt makes the
right behavior obvious, the server makes the wrong behavior impossible. Each layer
can tolerate the other's occasional failure.

### Why the step-first workflow pattern is load-bearing and must survive

The step-first pattern — boot prompt contains only "call `koan_complete_step`", step
guidance delivered as the tool's return value — was discovered empirically when Koan
was built on the original TS codebase. Weaker models (haiku-class) would receive a rich boot prompt and
produce a text response without calling any tool, causing the `-p` process to exit
immediately with no work done.

The solution has three reinforcement mechanisms that work together:

1. **Primacy**: the first thing the LLM reads is "call `koan_complete_step`". First
   instructions anchor the model's initial action.
2. **Recency**: `format_step()` always ends with "WHEN DONE: Call `koan_complete_step`".
   End-of-context instructions have disproportionate weight.
3. **Muscle memory**: by step 2, the model has already called the tool once and
   received a useful response. The pattern is established.

This same mechanism is observed in the `claude-config` skills framework
(`~/git/claude-config/skills/`), where `format_step()` ends with a `NEXT STEP: ...`
invoke block that the LLM must execute. The `MANDATORY INVOKE BLOCK` in
`roster_dispatch()` and `template_dispatch()` is the same pattern applied to
subagent launches. The skills framework independently validates that CLI-script-driven
step progression works across model capability levels.

In the Python rewrite, the MCP server returns the same formatted guidance as the
current `BasePhase`. The boot prompt ("You are a koan {role} agent. Call
`koan_complete_step` to receive your instructions.") is unchanged. Do not put task
content in the boot prompt — it breaks the pattern.

### Why file contracts are preserved (simplified)

`task.json`, `state.json`, and `events.jsonl` are already protocol-level
artifacts with runtime-agnostic JSON schemas and atomic rename semantics.

The schemas are preserved. What changed: `ipc.json` is eliminated entirely.
Tool calls that previously required file-based IPC are now in-process HTTP
request/response cycles within the driver. The driver writes `task.json`
before spawn, reads it at agent registration, and writes `state.json` +
`events.jsonl` as the audit trail — same data, fewer files, no polling.

### Why HTMX over React/Preact for the web rewrite

The current Preact + Zustand frontend has ~3000 lines of JSX, a bundling step
(`esbuild`), and a `node_modules` dependency. Every change to the dashboard requires
understanding the client-side state model (Zustand slices), the SSE dispatch layer
(`sse.js`), and the component tree. The two-process build (Python server + JS bundle)
adds friction.

HTMX inverts this: the server renders HTML fragments; the browser swaps them using
`hx-swap` on SSE events. The client has no state model — the server is the single
source of truth. For a dashboard that is fundamentally a view of server-side state
(pipeline phase, agent status, audit logs), this is the correct architecture.

Specific fit for Koan's patterns:

- SSE events already carry full state snapshots (phase, stories, agents, logs).
  HTMX's `hx-swap-oob` can handle out-of-band updates directly from SSE events.
- Token streaming maps to HTMX's SSE extension with `hx-target` pointing at the
  streaming text container.
- Question forms, artifact review, and workflow decision modals are server-rendered
  HTML; no client-side form state needed.
- Python backend (Starlette + Jinja2) means one language, one dependency manager,
  no build pipeline.

### The skills framework as proof of concept

Before this plan was written, the `~/git/claude-config/skills/` framework was studied
in detail. It demonstrates every core Koan mechanism without an extension runtime:

| Koan mechanism                                      | Skills framework analog                                                                                      |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `koan_complete_step` return value delivers guidance | `format_step(body, next_cmd)` output — the LLM reads the body and executes `next_cmd`                        |
| Boot prompt → first tool call → step 1 guidance     | `MANDATORY INVOKE BLOCK` in `roster_dispatch` — subagent must run the Python script before anything else     |
| `koan_ask_question` IPC flow                        | `<needs_user_input>` XML → orchestrator calls `AskUserQuestion` → reinvokes subagent with `--user-answer-id` |
| `koan_request_scouts` parallel dispatch             | `roster_dispatch()` — parallel subagent launches with shared context + unique tasks                          |
| Step state carried between calls                    | `--state-dir` flag + `plan.json` — state persists across reinvocations                                       |

The key difference: skills use **CLI reinvocation** (each step is a fresh process
invocation) while Koan uses **MCP persistence** (the MCP server holds state across
the child's lifetime). The MCP approach is richer because the child stays alive and
can do multi-step work within a single step, but the CLI pattern proves the
underlying step-guidance mechanism is agent-runtime-agnostic.

### Accepted losses from the TS codebase

These capabilities exist in the TypeScript codebase and are **not** replicated in the
Python rewrite. They are accepted losses, not gaps to fill:

- **Model registry / auth integration**: The TS dashboard discovers available
  models via the TS codebase's `ModelRegistry(AuthStorage)`. The Python rewrite uses a static
  config file (`~/.koan/config.json`) with explicit model IDs per runner. Users
  configure models manually. This is simpler and provider-agnostic.

- **TUI config commands**: The TS extension registers a `/koan config`
  interactive terminal command. The Python rewrite has no equivalent terminal UI.
  Model config is done via the web dashboard or CLI flags.

- **Bash truncation override**: The TS extension intercepts `tool_result` events for
  bash tools and raises the truncation limit from 50KB to 200KB. The Python rewrite
  does not replicate this. Each child CLI manages its own output limits.

- **Parent session conversation capture**: The TS `koan_plan` tool exports the
  parent conversation. Removed entirely — koan flows start fresh (see decision
  in "Resolved: CLI Protocol Research").

### The "one agent_id = one step state machine" invariant

This is the central constraint of the architecture. Each entry in the agent
registry owns:

- One role (e.g., `"intake"`)
- One step counter (starts at 0, advances on each `koan_complete_step` call)
- One permission set (derived from the role)
- One subagent directory (source of `task.json`, destination of `state.json`)
- One `EventLog` (append-only `events.jsonl` + `state.json`)

Violating this — by reusing an `agent_id` across phases, or sharing state
between registry entries — produces:

- **Permission state confusion**: role A's allowed tools bleed into role B's session
- **Step counter races**: two concurrent calls to `koan_complete_step` advance the
  same counter from different contexts
- **Audit attribution errors**: events logged with wrong role or wrong subagent ID

The invariant is enforced by lifecycle: the driver assigns a fresh `agent_id`
for every subagent spawn and registers a new entry in the dict. When the child
exits, the entry is deregistered. There is no pooling, no reuse, no sharing.

With HTTP transport, the server is shared but the state is not — `agent_id`
in the URL is the isolation boundary. The dict lookup is the first thing the
MCP endpoint does; an unknown `agent_id` returns an error immediately.

---

## Code Samples

### Agent registry + MCP endpoint (`koan/agents.py` + `koan/web/mcp.py`)

```python
# koan/agents.py
"""In-process agent registry. Maps agent_id → state for MCP tool dispatch."""
from dataclasses import dataclass, field
from koan.step_engine import StepEngine
from koan.permissions import PermissionFence
from koan.audit.log import EventLog


@dataclass
class AgentState:
    agent_id: str
    role: str
    subagent_dir: str
    epic_dir: str
    engine: StepEngine
    fence: PermissionFence
    event_log: EventLog


class AgentRegistry:
    """Thread-safe agent lookup. One entry per live subagent."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}

    async def register(self, agent_id: str, subagent_dir: str) -> AgentState:
        """Read task.json, init step engine + permissions + audit, store."""
        from koan.epic.state import read_task_file
        task = read_task_file(subagent_dir)
        engine = StepEngine(task, subagent_dir)
        fence = PermissionFence(task.role)
        event_log = EventLog(subagent_dir, task.role)
        await event_log.open()
        state = AgentState(agent_id, task.role, subagent_dir, task.epic_dir,
                           engine, fence, event_log)
        self._agents[agent_id] = state
        return state

    def get(self, agent_id: str) -> AgentState | None:
        return self._agents.get(agent_id)

    async def deregister(self, agent_id: str) -> None:
        state = self._agents.pop(agent_id, None)
        if state:
            await state.event_log.close()


# koan/web/mcp.py
"""MCP Streamable HTTP endpoint. All koan tools handled in-process."""
from starlette.requests import Request
from starlette.responses import JSONResponse
from koan.agents import AgentRegistry
from koan.tools import dispatch_tool


async def mcp_endpoint(request: Request) -> JSONResponse:
    """POST /mcp?agent_id={id} — MCP Streamable HTTP handler."""
    agent_id = request.query_params.get("agent_id")
    if not agent_id:
        return JSONResponse({"error": "missing agent_id"}, status_code=400)

    registry: AgentRegistry = request.app.state.registry
    agent = registry.get(agent_id)
    if not agent:
        return JSONResponse({"error": f"unknown agent: {agent_id}"}, status_code=404)

    body = await request.json()
    # MCP protocol: body contains method + params (tool name, arguments)
    tool_name = body.get("params", {}).get("name")
    tool_args = body.get("params", {}).get("arguments", {})

    # Permission check before dispatch
    perm = agent.fence.check(tool_name, agent.engine.current_step,
                             agent.epic_dir, tool_args)
    if not perm.allowed:
        return _mcp_error(perm.reason)

    # Dispatch to tool handler — blocks until complete (may await user input)
    result = await dispatch_tool(tool_name, tool_args, agent, request.app)
    return _mcp_result(result)
```

### Step engine (`koan/step_engine.py`)

```python
"""Step state machine — one instance per MCP server (one per subagent)."""
from dataclasses import dataclass, field
from typing import Callable, Awaitable
import koan.phases as phases_registry
from koan.phases.base import PhaseContext, StepGuidance


@dataclass
class StepEngine:
    task: object              # SubagentTask (role, epic_dir, etc.)
    subagent_dir: str
    _step: int = field(default=0, init=False)
    _phase_ctx: PhaseContext = field(init=False)

    # Callback set by review-gated phases; blocks koan_complete_step until called.
    on_complete_step: Callable[[str], Awaitable[str | None]] | None = field(
        default=None, init=False
    )

    def __post_init__(self) -> None:
        self._phase_ctx = PhaseContext(
            epic_dir=self.task.epic_dir,
            subagent_dir=self.subagent_dir,
            phase_instructions=getattr(self.task, "phase_instructions", None),
        )
        phase_mod = phases_registry.get(self.task.role)
        self._phase = phase_mod  # module with system_prompt(), step_guidance(), etc.

    @property
    def current_step(self) -> int:
        return self._step

    @property
    def role(self) -> str:
        return self.task.role

    async def advance(self, thoughts: str) -> str:
        """Advance step; return next guidance or 'Phase complete.'"""
        if self._step == 0:
            # Boot transition: establish the call→receive→work→call pattern.
            self._step = 1
            guidance = self._phase.step_guidance(1, self._phase_ctx)
            return _format_step(guidance)

        # Pre-condition check before advancing (e.g., review acceptance gate).
        error = await self._phase.validate_step_completion(self._step, self._phase_ctx)
        if error:
            return error  # LLM sees error and must fix the pre-condition

        next_step = self._phase.get_next_step(self._step, self._phase_ctx)
        if next_step is None:
            return "Phase complete."

        prev = self._step
        self._step = next_step
        if next_step < prev:                      # loop-back (e.g., intake confidence loop)
            await self._phase.on_loop_back(prev, next_step, self._phase_ctx)

        guidance = self._phase.step_guidance(next_step, self._phase_ctx)
        return _format_step(guidance)
```

### Permission fence (`koan/permissions.py`)

```python
"""Default-deny role-based permission enforcement. Called on every tool invocation."""
import os
from dataclasses import dataclass

# Always allowed — distinguishing 'read bash' from 'write bash' is intractable.
READ_TOOLS = frozenset({"read", "bash", "grep", "glob", "find", "ls"})
WRITE_TOOLS = frozenset({"edit", "write"})

# Planning roles: write access path-scoped to epic_dir only.
PLANNING_ROLES = frozenset({
    "intake", "scout", "decomposer", "brief-writer",
    "orchestrator", "planner", "workflow-orchestrator",
})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "intake":      frozenset({"koan_complete_step", "koan_ask_question",
                               "koan_request_scouts", "koan_review_artifact",
                               "edit", "write"}),
    "executor":    frozenset({"koan_complete_step", "koan_ask_question",
                               "edit", "write", "bash"}),
    # ... other roles
}

# Step 1 of intake/brief-writer is read-only comprehension.
STEP_1_BLOCKED = frozenset({"koan_request_scouts", "koan_ask_question", "write", "edit"})


@dataclass
class PermissionResult:
    allowed: bool
    reason: str = ""


def check_permission(
    role: str,
    tool_name: str,
    current_step: int,
    epic_dir: str | None = None,
    tool_args: dict | None = None,
) -> PermissionResult:
    if tool_name in READ_TOOLS:
        return PermissionResult(allowed=True)

    # Step-level read-only gates.
    if role in ("intake", "brief-writer") and current_step == 1:
        if tool_name in STEP_1_BLOCKED:
            return PermissionResult(
                allowed=False,
                reason=f"{tool_name} not available during step 1 (read-only).",
            )

    if role not in ROLE_PERMISSIONS:
        return PermissionResult(allowed=False, reason=f"Unknown role: {role}")

    if tool_name not in ROLE_PERMISSIONS[role]:
        return PermissionResult(allowed=False,
                                reason=f"{tool_name} not available for role {role}")

    # Path-scope enforcement for planning roles.
    if tool_name in WRITE_TOOLS and role in PLANNING_ROLES and epic_dir and tool_args:
        raw_path = tool_args.get("path", "")
        if raw_path and not os.path.realpath(raw_path).startswith(
            os.path.realpath(epic_dir) + os.sep
        ):
            return PermissionResult(
                allowed=False,
                reason=f"{tool_name} path outside epic directory.",
            )

    return PermissionResult(allowed=True)
```

### Runner protocol (`koan/runners/base.py` + implementations)

```python
# koan/runners/base.py
"""Abstract runner interface. All runners point children at the driver's HTTP MCP endpoint."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class StreamEvent:
    """Normalized output from any child agent's stdout stream."""
    kind: str        # "text_delta" | "thinking_delta" | "turn_end"
    delta: str = ""


class Runner(Protocol):
    name: str

    def build_command(
        self, boot_prompt: str, mcp_url: str, model: str | None, cwd: str
    ) -> list[str]: ...

    def write_mcp_config(self, mcp_url: str, config_dir: str) -> str:
        """Write MCP config for this CLI. Returns path to config file."""
        ...

    def parse_stream_event(self, line: str) -> StreamEvent | None: ...


# koan/runners/claude.py
import json, os
from koan.runners.base import Runner, StreamEvent


class ClaudeRunner:
    name = "claude"

    def build_command(self, boot_prompt, mcp_url, model, cwd):
        config_path = self.write_mcp_config(mcp_url, cwd)
        args = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose", "--include-partial-messages",
            "--mcp-config", config_path,
            "--strict-mcp-config",
            "--dangerously-skip-permissions",
        ]
        if model:
            args += ["--model", model]
        args.append(boot_prompt)
        return args

    def write_mcp_config(self, mcp_url, config_dir):
        path = os.path.join(config_dir, ".koan-mcp.json")
        with open(path, "w") as f:
            json.dump({"koan": {"type": "http", "url": mcp_url}}, f)
        return path

    def parse_stream_event(self, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return None
        if ev.get("type") == "stream_event":
            inner = ev.get("event", {})
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    return StreamEvent(kind="text_delta", delta=delta.get("text", ""))
        if ev.get("type") == "result":
            return StreamEvent(kind="turn_end")
        return None


# koan/runners/codex.py
class CodexRunner:
    """Codex: -c runtime overrides for HTTP MCP. Per-process, not persisted."""
    name = "codex"

    def build_command(self, boot_prompt, mcp_url, model, cwd):
        args = [
            "codex", "exec", "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "-c", f'mcp_servers.koan.url="{mcp_url}"',
        ]
        if model:
            args += ["-m", model]
        args.append(boot_prompt)
        return args

    def write_mcp_config(self, mcp_url, config_dir):
        return ""  # codex uses -c flags, no config file needed

    def parse_stream_event(self, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return None
        if ev.get("type") == "item.completed":
            item = ev.get("item", {})
            if item.get("type") == "agent_message":
                return StreamEvent(kind="text_delta", delta=item.get("text", ""))
        if ev.get("type") == "turn.completed":
            return StreamEvent(kind="turn_end")
        return None


# koan/runners/gemini.py
class GeminiRunner:
    """Gemini: .gemini/settings.json in cwd for HTTP MCP config."""
    name = "gemini"

    def build_command(self, boot_prompt, mcp_url, model, cwd):
        self.write_mcp_config(mcp_url, cwd)
        args = ["gemini", "-p", boot_prompt, "-o", "stream-json",
                "--yolo", "--allowed-mcp-server-names", "koan"]
        if model:
            args += ["-m", model]
        return args

    def write_mcp_config(self, mcp_url, config_dir):
        import os
        gemini_dir = os.path.join(config_dir, ".gemini")
        os.makedirs(gemini_dir, exist_ok=True)
        path = os.path.join(gemini_dir, "settings.json")
        with open(path, "w") as f:
            json.dump({"mcpServers": {"koan": {"type": "http", "url": mcp_url}}}, f)
        return path

    def parse_stream_event(self, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return None
        if ev.get("type") == "message" and ev.get("role") == "assistant" and ev.get("delta"):
            return StreamEvent(kind="text_delta", delta=ev.get("content", ""))
        if ev.get("type") == "result":
            return StreamEvent(kind="turn_end")
        return None
```

### Phase module interface (`koan/phases/intake.py`)

```python
"""Intake phase: 5-step linear workflow producing landscape.md."""
from koan.phases.base import PhaseContext, StepGuidance

ROLE = "intake"
TOTAL_STEPS = 5
REVIEW_GATED_STEP = 5   # Step 5 (Synthesize) requires koan_review_artifact acceptance.

STEP_NAMES = {1: "Extract", 2: "Scout", 3: "Ask", 4: "Reflect", 5: "Write"}


def system_prompt() -> str:
    return (
        "You are an intake analyst for a coding task planner. You read a conversation "
        "history, explore the codebase, and ask the user targeted questions until you "
        "have complete context for planning.\n\n"
        "Your output — landscape.md — is the sole foundation for all downstream work.\n\n"
        "## Tools\n"
        "- Read tools (read, bash, grep, glob, find, ls)\n"
        "- `koan_request_scouts` — parallel codebase exploration\n"
        "- `koan_ask_question` — structured user questions\n"
        "- `koan_review_artifact` — present landscape.md for review (step 5 only)\n"
        "- `koan_complete_step` — signal step completion"
    )
    # Note: no forbidden tool list. Positive guidance only.
    # The MCP server enforces the fence; the prompt guides toward correct usage.


def step_name(step: int) -> str:
    return STEP_NAMES.get(step, f"Step {step}")


def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    """Return step instructions. Called by StepEngine.advance() after boot transition."""
    if step == 1:
        return StepGuidance(
            title="Extract",
            instructions=[
                f"Read {ctx.epic_dir}/conversation.jsonl.",
                "Build a mental model of the task. Do NOT call scouts or ask questions yet.",
                "WHEN DONE: Call koan_complete_step.",
            ],
        )
    # ... steps 2–5
    raise ValueError(f"Invalid step {step} for intake phase")


def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    """Pure function. For intake, steps progress linearly 1→5, then done."""
    if step >= TOTAL_STEPS:
        return None
    return step + 1


async def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    """Block koan_complete_step on step 5 until review is accepted."""
    if step == REVIEW_GATED_STEP:
        if not ctx.last_review_accepted:
            return (
                "You must call koan_review_artifact on landscape.md before completing "
                "this step. Write landscape.md, then invoke koan_review_artifact."
            )
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    """No-op for linear intake. Confidence-gated loop variant would reset state here."""
    pass
```

## Resolved: CLI Protocol Research

### MCP config injection — HTTP transport (verified 2026-03-26)

All three CLIs support HTTP MCP servers. Each runner writes a config pointing
at `http://localhost:{port}/mcp?agent_id={id}`:

**Claude Code:** `--mcp-config <file>` with `--strict-mcp-config` for isolation:

```json
{
  "koan": {
    "type": "http",
    "url": "http://localhost:8420/mcp?agent_id=intake-abc123"
  }
}
```

**Codex:** `-c` runtime config override (per-process, not persisted):

```bash
codex exec -c 'mcp_servers.koan.url="http://localhost:8420/mcp?agent_id=intake-abc123"' ...
```

**Gemini:** `.gemini/settings.json` in cwd + `--allowed-mcp-server-names koan`:

```json
{
  "mcpServers": {
    "koan": {
      "type": "http",
      "url": "http://localhost:8420/mcp?agent_id=intake-abc123"
    }
  }
}
```

### MCP server lifecycle (decided 2026-03-26)

The driver starts one HTTP server **before** any subagents. Children connect
to it — no per-subagent server processes. The flow:

1. Driver starts Starlette app on `localhost:{port}`
2. For each subagent: assign `agent_id`, write `task.json`, register agent
   in registry (reads `task.json`, inits step engine + permissions)
3. Write MCP config pointing at `http://localhost:{port}/mcp?agent_id={id}`
4. Spawn child agent with that config
5. Child connects to the driver's MCP endpoint via HTTP
6. Tool calls arrive as HTTP requests, dispatched by `agent_id`
7. Child exits → driver deregisters `agent_id`

### Boot prompt delivery (verified 2026-03-26)

Both CLIs accept a boot prompt as a positional argument in print mode:

- **claude:** `claude -p "prompt"` — positional arg. Also `--system-prompt`.
- **codex:** `codex exec "prompt"` — positional arg. Also stdin via `-`.
- **gemini:** `gemini -p "prompt"` — via `-p` flag (not positional).

All support non-interactive print mode. The runner abstraction handles the
minor flag differences (`-p` vs `exec` vs `-p "prompt"`).

### Conversation capture (decided 2026-03-26)

**Removed entirely.** Koan flows start fresh — there is no parent conversation
to capture. The previous behavior (exporting `sessionManager` content to
`conversation.jsonl`) assumed Koan was triggered from within an agent session.

In standalone mode, Koan is invoked directly from the CLI. Context comes from:

- The user's initial prompt (passed as CLI argument or via the web UI)
- Codebase exploration during the intake phase
- User Q&A during intake

Future work may add "forking" from an existing coding agent conversation, but
this is explicitly out of scope for the rewrite.

### Token streaming formats (verified 2026-03-26)

**Claude Code** (`-p --output-format stream-json --verbose --include-partial-messages`):

JSONL with `"type"` field. True incremental token deltas:

```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_delta",
    "index": 0,
    "delta": { "type": "text_delta", "text": "Hello" }
  }
}
```

Also emits `message_start`, `content_block_start/stop`, `message_delta`
(with `stop_reason`), `message_stop`, and final `result` with usage/cost.
Tool calls appear as `content_block_start` with `type: "tool_use"`.

**Codex** (`exec --json`):

JSONL, but **no incremental token streaming** — only turn-level events:

```json
{"type":"thread.started","thread_id":"..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Hello from Codex"}}
{"type":"turn.completed","usage":{"input_tokens":11388,"cached_input_tokens":9344,"output_tokens":24}}
```

The complete message text arrives in one `item.completed` event. There are no
incremental `text_delta` events. Token streaming display will show nothing
until the turn completes, then show the full text. This is a known limitation
of the Codex runner.

**Gemini** (`-p -o stream-json`):

JSONL with incremental streaming via `delta:true`:

```json
{"type":"init","timestamp":"...","session_id":"...","model":"auto-gemini-3"}
{"type":"message","timestamp":"...","role":"user","content":"say hello"}
{"type":"message","timestamp":"...","role":"assistant","content":"Hello there, friend.","delta":true}
{"type":"result","timestamp":"...","status":"success","stats":{"total_tokens":13637,...}}
```

Messages with `"delta":true` are incremental assistant output. The `result`
event carries usage statistics including per-model breakdowns (gemini uses
multi-model routing internally).

**Normalized StreamEvent mapping:**

| Normalized kind  | Claude source                                   | Codex source                                  | Gemini source                                 |
| ---------------- | ----------------------------------------------- | --------------------------------------------- | --------------------------------------------- |
| `text_delta`     | `stream_event.event.delta.type == "text_delta"` | `item.completed` (full text, not incremental) | `message` with `role=assistant, delta=true`   |
| `thinking_delta` | `stream_event.event.delta.type == "thinking"`   | N/A                                           | N/A (thinking tokens counted but not exposed) |
| `tool_use_start` | `content_block_start.type == "tool_use"`        | N/A                                           | N/A                                           |
| `turn_end`       | `type == "result"`                              | `type == "turn.completed"`                    | `type == "result"`                            |
| `usage`          | `result.usage`                                  | `turn.completed.usage`                        | `result.stats`                                |

### Audit trail source (decided 2026-03-26)

The activity feed and audit trail are populated **entirely from the child
agent's JSON stdout stream**, not from MCP server hooks. The runner parses
stdout for both token streaming and tool-call-level events. The MCP server
contributes only koan-specific events (step transitions, phase start/end).

This means:

- No `tool_call` / `tool_result` hooks needed in the MCP server
- The runner is the sole source of native tool visibility
- Audit completeness depends on the runner's stream parser quality
- Different CLIs may expose different levels of tool detail in their output

---

## Open Questions

1. **Claude `--strict-mcp-config` + HTTP**: Does `--strict-mcp-config`
   work correctly with HTTP MCP servers (not just stdio)? Need to verify
   it doesn't break claude's built-in tools.

2. **Codex HTTP MCP**: Does `-c 'mcp_servers.koan.url="http://..."'`
   work for HTTP transport? The `-c` per-process override was confirmed,
   but only with stdio `command`/`args` format. Need to test with `url`.

3. **Gemini HTTP MCP config format**: Verify that
   `{"type":"http","url":"..."}` is the correct format in
   `.gemini/settings.json` for HTTP transport.

4. **Codex token streaming gap**: Codex only emits `item.completed` with
   the full message — no incremental deltas. Dashboard token streaming
   will be blank during Codex turns. Acceptable, or investigate further.

5. **MCP Streamable HTTP implementation**: Which Python MCP SDK library
   supports the Streamable HTTP transport server-side? Verify
   `mcp[server]` supports mounting as a Starlette route.

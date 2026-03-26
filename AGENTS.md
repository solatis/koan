# Koan Architecture Invariants

Full architecture documentation: **[docs/architecture.md](docs/architecture.md)**

Spoke documents:

- [docs/subagents.md](docs/subagents.md) -- spawn lifecycle, task manifest, step-first workflow, permissions
- [docs/ipc.md](docs/ipc.md) -- HTTP MCP tool calls, blocking interactions, scout spawning
- [docs/state.md](docs/state.md) -- driver/LLM boundary, epic and story state, routing rules
- [docs/intake-loop.md](docs/intake-loop.md) -- confidence-gated loop, non-linear step progression, prompt engineering
- [docs/epic-brief.md](docs/epic-brief.md) -- brief artifact, brief-writer subagent, downstream references
- [docs/artifact-review.md](docs/artifact-review.md) -- artifact review protocol, review loop, reusability
- [docs/token-streaming.md](docs/token-streaming.md) -- runner stdout parsing, SSE delta path

**Pipeline phases:** `intake` -> `brief-generation` -> `core-flows` -> `tech-plan` -> `ticket-breakdown` -> `cross-artifact-validation` -> `execution` -> `implementation-validation` -> `completed`

---

The six core invariants (see architecture.md for full detail + pitfalls):

## 1. File Boundary

LLMs write **markdown files only**. The driver maintains **JSON state files**
internally -- no LLM ever reads or writes a `.json` file. Tool code bridges
both worlds.

## 2. Step-First Workflow Pattern (critical)

Every subagent is a CLI process (`claude`, `codex`, or `gemini`) that connects
to the driver's HTTP MCP endpoint at `http://localhost:{port}/mcp?agent_id={id}`.
The subagent receives tools via MCP and calls them over HTTP. The driver handles
all tool logic in-process.

**The first thing any subagent does is call `koan_complete_step`.** The spawn
prompt contains _only_ this directive. The tool returns step 1 instructions.
This establishes the calling pattern before the LLM sees complex instructions.

```
Boot prompt:  "You are a koan {role} agent. Call koan_complete_step to receive your instructions."
     | LLM calls koan_complete_step (step 0 -> 1 transition)
Tool returns:  Step 1 instructions (rich context, task details, guidance)
     | LLM does work...
     | LLM calls koan_complete_step
Tool returns:  Step 2 instructions (or "Phase complete.")
```

Step progression is normally linear, but phase modules may override
`get_next_step()` to implement non-linear flows. The intake phase loops steps
2-4 until a confidence gate is satisfied. See
[docs/intake-loop.md](docs/intake-loop.md).

## 3. Driver Determinism

The driver (`koan/driver.py`) reads JSON state files and exit codes, applies
routing rules, and spawns the next subagent. It never makes judgment calls or
parses free-text.

## 4. Default-Deny Permissions

Every tool call passes through a role-based permission fence. Unknown roles
and tools are blocked. Planning roles can only write inside the epic directory.

The fence also supports step-level gating for individual roles: the intake
phase blocks side-effecting tools during its read-only Extract step (step 1).

## 5. Need-to-Know Prompts

Boot prompt is one sentence. System prompt has role identity, no task details.
Task details arrive via step 1 guidance after the tool-calling pattern is
established.

## 6. Directory-as-Contract

The subagent directory is the sole interface between parent and child.
Two well-known JSON files plus the MCP endpoint URL:

| File           | Writer                    | Reader                         | Purpose            |
| -------------- | ------------------------- | ------------------------------ | ------------------ |
| `task.json`    | Parent (before spawn)     | Parent (at agent registration) | What to do         |
| `state.json`   | Parent (audit projection) | Available for debugging        | What has been done |
| `events.jsonl` | Parent (audit log)        | Available for replay           | Full event history |

The `mcp_url` field in `task.json` tells the child where to connect for tool
calls. No structured configuration flows through CLI flags. The spawn command
carries the directory path and the MCP config pointing at the driver's HTTP
endpoint.

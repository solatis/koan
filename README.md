# Koan Pi Package

## Overview

Koan is an opinionated planning workflow extension for the pi coding agent. It constrains model behavior with deterministic phase orchestration, explicit tool boundaries, and durable file-backed state so planning sessions are repeatable and auditable.

## Architecture

The runtime is split into two modes from the same extension entrypoint:

- **Parent session mode** registers the `koan_plan` MCP tool and the `/koan-execute`, `/koan-status` commands. The parent orchestrates the full workflow when `koan_plan` is invoked.
- **Subagent mode** runs role/phase-specific workflows (architect, developer, technical writer, QR decomposer, reviewer, fix mode).

The parent controls progression through plan design, plan code, plan docs, quality review, and iterative fixes. Subagents are isolated processes that communicate through persisted artifacts (`plan.json`, `qr-*.json`) and audit projections.

## Invoking the Planner

Call `koan_plan` as an MCP tool — the LLM invokes it when the user asks to plan a complex task. No parameters are needed: the conversation up to that point is automatically exported to `conversation.jsonl` in the plan directory and becomes the planning context.

The planning pipeline runs sequentially:

1. **plan-design** (architect) — reads `conversation.jsonl` to understand intent, explores the codebase, writes `plan.json`.
2. **plan-code** (developer) — reads `plan.json`, populates code intents and changes.
3. **plan-docs** (technical writer) — reads `plan.json` and optionally `conversation.jsonl` for decisions and tradeoffs, writes documentation entries.

Each phase is followed by a QR (quality review) block: decompose → parallel verify → fix loop, up to `MAX_FIX_ITERATIONS`.

### conversation.jsonl

Written once at the start of `koan_plan`. Contains the full session branch as JSONL (one JSON object per line — raw pi `SessionManager` entries, not a plain-text transcript). The plan-design architect and plan-docs writer are told about this file and may `Read` it; other phases work from `plan.json` only.

### Prompt + convention sources

- Subagent system prompts are hard-coded in `src/planner/lib/agent-prompts.ts`.
- Convention docs stay file-based in `resources/conventions` and are surfaced to prompts via `CONVENTIONS_DIR`.

### Slash commands

| Command | Description |
|---|---|
| `/koan-execute` | Execute a koan plan (not yet implemented) |
| `/koan-status` | Show current workflow phase |

## Design Decisions

Key design choices that shape implementation:

- **Inversion of control**: TypeScript orchestration code drives agent behavior; models do not self-route workflow steps.
- **Tool-call-driven transitions**: step progression happens via `koan_complete_step` tool calls, not conversational chaining.
- **Default-deny permissions**: each phase explicitly allowlists tools; unknown tool/phase access is blocked.
- **Disk-backed mutations**: planning mutations are immediately persisted with atomic writes instead of deferred finalize steps.
- **Need-to-know prompts**: each subagent only receives the minimum context needed for its task.
- **Passive conversation context**: `conversation.jsonl` is a read-only artifact on disk. No phase programmatically injects it into prompts; agents that need it use the `Read` tool.

## Invariants

The workflow depends on these invariants:

- Planning phases must block direct `edit`/`write` tools.
- Tool failures must throw errors (not return soft error payloads).
- Cross-reference integrity in the plan must validate before progression.
- MUST-severity QR failures remain blocking even as lower-severity checks de-escalate in later fix iterations.

## Boundaries

Current scope focuses on planning and QR orchestration. `/koan-execute` is intentionally not implemented yet.

# Koan

Koan runs opinionated multi-turn workflows for LLM-assisted engineering. A local Python process hosts a web dashboard and an MCP endpoint; subagents are invocations of the vendor CLIs (`claude`, `codex`, or `gemini`) that connect back over HTTP MCP and advance through a fixed sequence of phases under user direction. Decisions are written to markdown artifacts during the run, and a per-project memory is carried across runs.

Koan invokes the vendor CLIs as subprocesses and uses whatever authentication they already have on your machine. It does not call provider APIs directly, does not touch OAuth credentials, and does not proxy traffic, so it runs under your existing CLI subscription and within each CLI's terms of service.

Koan is alpha. Interfaces, phase names, state files, and the memory schema will change without migration.

## The Problem

Long-lived LLM-assisted projects accumulate what I call knowledge debt. The developer no longer knows what is in the code, and the LLM never knew to begin with. Utilities get reimplemented, conventions diverge, and architecture drifts.

LLMs are good at retrieval, synthesis, and presentation. They are bad at reasoning under uncertainty and at noticing drift. Larger context windows do not help -- attention is finite and uneven regardless of window size. What helps is giving the model a narrower slice of the right information at each step, and writing the decisions down so the next run does not re-derive them.

## What It Does

### Workflows

A workflow is a fixed sequence of phases with narrow roles. The plan workflow runs intake, plan-spec, plan-review, execute. The orchestrator is a long-lived LLM process that advances by calling typed tools; it cannot skip phases or improvise structure. Each phase ends with a summary and a pause for user direction.

### Decision capture

Agents write markdown artifacts during the run: landscape.md, plan.md, scout findings, review notes. These are the durable record of what was considered and why.

### Memory

A per-project memory lives under `.koan/memory/`. Each entry is a short markdown file with YAML frontmatter, typed as decision, context, lesson, or procedure. Entries are proposed by the orchestrator at the end of a workflow and approved by the user before being committed.

Three read modes are exposed to agents:

- `status`: a broad project summary, injected at workflow start
- `query`: hybrid semantic + keyword retrieval
- `reflect`: the agent poses a question and receives a synthesized briefing drawn from multiple entries

Phase entry also retrieves a contextual slice of memory, scoped to the role and phase.

### Machine-readable code

Function docstrings are written for LLM consumption. They include usage examples and explicit "use when..." triggers, so an agent reading the docstring can decide whether the function applies without reading the body.

### Docs in code

Architecture decisions and invariants live next to the code they constrain. Workflows read and update these during execution rather than deferring to a cleanup pass.

### Conventions

Project conventions are declared, not inferred. Agents check against them during review.

## Quick Start

```bash
uv sync
uv run koan
```

Open the dashboard, select a workflow, and describe the task.

## How a Run Looks

The plan workflow phases:

- `intake`: explore the codebase, ask clarifying questions, produce landscape.md
- `plan-spec`: produce plan.md
- `plan-review`: adversarial review of plan.md against landscape.md
- `execute`: spawn an executor with plan.md

Memory is consulted at intake and at each phase boundary. At the end of the run, curation proposes memory additions for user approval.

## Design Notes

A single Python process (`koan/driver.py`) hosts the dashboard and the MCP endpoint. Subagents are CLI processes speaking HTTP MCP. The driver validates phase transitions, enforces a default-deny permission fence, and maintains run state. It does not parse LLM output. Agents write markdown; the driver writes JSON.

Three roles:

- `orchestrator`: runs the workflow and delegates
- `scout`: parallel, read-only investigator
- `executor`: implements from an approved plan

## Status

Alpha. I use it daily across several projects. Interfaces will change.

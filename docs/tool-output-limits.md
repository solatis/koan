# Tool Output Limits

Design decision document for how a tool result is bounded before it enters
model history, and why the bound differs by the tool's **trust class**.

> Parent doc: [architecture.md](./architecture.md)

---

## The problem

Every tool result is appended to the agent's `message_history` and re-sent on
the next model request (`koan/agents/loop.py`). The model-visible history is the
scarce resource: providers reject requests past their input-token ceiling
(Gemini ~1M). A single oversized result -- a `read` of a minified bundle, a
`bash` that cats a log -- can blow the budget after a handful of calls.

This is not hypothetical. A `plan` run failed mid-intake after **three** tool
results pushed the next request past 1,048,576 tokens:

```
status_code: 400, model_name: gemini-3.1-pro-preview,
body: 'The input token count exceeds the maximum number of tokens allowed (1048576).'
```

A second incident (2026-07-14) showed that a **record cap alone is not a size
bound**: a `grep` over `koan/koan` matched two single-line sourcemaps (5.2 MB
and 1.8 MB) under the bundled frontend assets. Only 133 match lines -- well
under the 500-record cap -- but 7 MB of output, permanently poisoning the
history: every subsequent request failed HTTP 400 "prompt too long". This is
why records are also counted against a cumulative **byte budget** (below).

So the invariant is: **every tool result MUST be bounded before it lands in
history.** The strategy question is not _whether_ to bound but _how_ -- and the
answer depends on who controls the producer.

---

## Trust classes

The bound koan applies depends on whether koan controls the content's size and
shape. This splits the tool vocabulary into two classes.

### Untrusted results -- cap at limit

Tools that surface content koan neither produces nor shapes: `read`, `grep`,
`glob`, `bash`. The size and structure are opaque -- koan cannot meaningfully
summarize arbitrary file bytes or command output, because it does not know what
in them matters to the caller.

**Rule:** cap each tool's output _pre-emptively_ via two coexisting bounds --
a `limit` record cap (default `DEFAULT_LIMIT = 500` in
`koan/tools/builtin_tools.py`) and a cumulative **byte budget** (default
`DEFAULT_TOOL_RESULT_MAX_BYTES = 32 KiB` in `koan/tools/byte_budget.py`) --
whichever fires first stops processing. Capped results are returned with a
truncation note; no total count is computed (computing totals requires
processing everything, which defeats both context-window protection and
execution-time limiting). The model can override `limit` via the tool
parameter; the byte budget is internal-only, so tool schemas stay byte-stable.

- **Generator-style processing:** `grep` iterates files and lines and stops
  when `limit` match lines are collected or the byte budget fills -- remaining
  files are not read. `glob` iterates the filesystem and stops when `limit`
  paths are found. `bash` streams output via `subprocess.Popen` and kills the
  process when `limit` lines or the byte budget are reached.
- **Byte budgets (two layers):** `ByteBudget` counts each record's UTF-8
  bytes (joiner included) as it is collected; the record that overflows is
  clipped to the remaining budget (its `file:lineno:` prefix stays visible so
  the model can exclude the offending file) and processing stops -- an
  execution bound, same virtue as the record cap. Above the in-tool budget
  sits `ByteBudgetToolset` (`TOOL_RESULT_CEILING_BYTES = 64 KiB`, 2x the
  budget), a `WrapperToolset` around the builtin toolset at agent assembly
  (`koan/agents/pydantic_ai.py`): the mechanical invariant that no builtin
  result above the ceiling ever enters history, regardless of per-tool
  accounting. In-tool budget < ceiling so the informative in-tool notes are
  what the model normally sees; the ceiling catches slack (headers, notes)
  and tools without their own byte bound.
- **`read` is a special case:** anchors must be computed over the whole file
  (collision disambiguation via `~N` ordinals depends on file order), so the
  full file is read internally even when only `limit` lines are returned. The
  output is sliced to `limit` lines via `render_anchored`, then truncated to
  the byte budget post-render (no early-stop win exists; the note advises
  `offset`/`limit` paging).
- **`glob` results come in filesystem traversal order** (not sorted), because
  sorting requires collecting all matches before capping, which defeats the
  early-stop goal.
- **`grep` candidate enumeration (discovery + sort) is eager** -- file
  discovery is not bounded by `limit`; only file reads and line scans are. The
  dominant cost (reading files and searching line-by-line) is bounded.
- **Truncation notes:** capped results append a note indicating capping and
  suggesting how to narrow (e.g. "Results capped at 500 match lines -- narrow
  the pattern or path to see more."). No total count is reported.
- **Ignored directories:** `glob` and `grep` additionally skip `_IGNORED_DIRS`
  (`.git`, `node_modules`, `__pycache__`, `.venv`, `.env`, `build`, `cache`),
  so a repo-root search is scoped to source files and does not trip the cap
  on dependency trees before the model even sees a result.

### Trusted results -- bound by construction

Tools koan implements end to end, returning a koan-defined schema:
`koan_search`, `koan_reflect`, `koan_memory_status`, `koan_artifact_list`, and
the control-ack tools (`koan_set_phase`, `koan_suggest_next`, ...).

`koan_artifact_read/write/edit` are also in this class. They are **trusted,
run-dir-scoped wrappers** over the built-in `read`/`write`/`edit`: koan authored
the run-dir artifact, so its content is bounded by construction and prompting.
`koan_artifact_read` calls `read_tool(..., limit=None, max_bytes=None)` -- it
is **exempt** from the untrusted output caps (both the record cap and the
byte budget; the `ByteBudgetToolset` ceiling wraps only the builtin toolset,
so koan\_\* tools are not subject to it either). A large artifact is returned
in full; `offset`/`limit` are available for paging convenience but impose no
hard cap. See [tools.md](./tools.md).

**Rule:** bound the output **at the source**, deterministically and
structure-aware. **Never reject** -- koan caused the size and owns the schema,
and the model usually has _no_ narrowing lever for a koan tool (it cannot
"narrow" a spec it was instructed to read). Rejecting a trusted tool would be a
dead end; the producer must instead guarantee a bounded, semantically coherent
result.

Bounding techniques, by output kind:

| Output kind        | Technique                            | Example                                        |
| ------------------ | ------------------------------------ | ---------------------------------------------- |
| Count-bounded list | cap item count server-side           | `koan_search` clamps `k`; `koan_artifact_list` |
| Field-bounded item | cap unbounded fields + return handle | memory `body` -> first N chars + `entry_id`    |
| Paginated document | expose `offset`/`limit` like `read`  | `koan_search` snippets; large reads via paging |
| Generated text     | cap at the producer's `max_tokens`   | `koan_reflect` answer                          |
| Control ack        | fixed-size status string             | `koan_set_phase`, `koan_suggest_next`          |

### Web tools -- bound by request (a sub-case of untrusted)

`web_fetch` / `web_search` are untrusted in origin, but the **model declares the
budget up front** via a parameter (`max_chars`, default 20000; `max_results`,
default 5). Truncate-to-budget is acceptable here because the model opted into
the size and the truncation point is its own choice. These do **not** route
through the pre-emptive cap -- the request parameter _is_ the bound.

---

## Invariants

1. **No tool result enters history unbounded.** Every result is either under an
   enforced ceiling, shaped to a bounded schema, or truncated to a
   caller-declared budget. For the builtin (untrusted) toolset this is
   enforced mechanically by the `ByteBudgetToolset` ceiling, not just by
   per-tool discipline.
2. **Untrusted = cap at limit; trusted = shape; never the reverse.** Untrusted
   tools cap at the pre-emptive `limit`/byte budget and return partial
   results; trusted tools bound by construction and never cap (the model
   cannot narrow them). The byte ceiling applies to the untrusted toolset
   only -- trusted koan\_\* tools remain uncapped by design.
3. **Single source of truth for limits.** The untrusted default record cap
   lives as `DEFAULT_LIMIT` in `koan/tools/builtin_tools.py`; the byte
   constants (`DEFAULT_TOOL_RESULT_MAX_BYTES`, `TOOL_RESULT_CEILING_BYTES`)
   live in `koan/tools/byte_budget.py`. Trusted caps live with their producer
   in `koan/tools/koan_tools.py`. No magic numbers scattered at call sites.
4. **Capping is observable.** When an untrusted tool caps its output it appends a
   truncation note to the result (and the projection feed shows the
   tool_result). Trusted-side caps should note in the result when they elided
   content, so a debugged blowup can be traced to its source.
5. **Conservative by default.** Ceilings start low and are raised only with
   evidence. A too-tight ceiling costs an extra narrowing round-trip; a too-loose
   one costs the whole run.

---

## Known gaps (as of 2026-07-14)

The untrusted side is bounded by the pre-emptive `limit` parameter, the
cumulative byte budget, and the `ByteBudgetToolset` ceiling. The trusted side
is **not yet uniformly bounded by construction** -- these are the open items:

- ~~The artifact reader had no bound and no pagination.~~ **Fixed:** now
  `koan_artifact_read`, a trusted wrapper that bypasses the untrusted caps
  (`limit=None, max_bytes=None`); `offset`/`limit` page for convenience with
  no hard cap. See [tools.md](./tools.md).
- ~~A single long record defeated the record cap (the 7 MB sourcemap grep).~~
  **Fixed:** cumulative byte budgets in every untrusted tool plus the
  toolset-level ceiling (`koan/tools/byte_budget.py`).
- **`koan_search` returns the full `body` of each of `k` entries.** `k` is
  bounded but per-entry `body` is not. Should field-bound `body` (first N chars +
  `entry_id`), so the count cap is also a size cap. (Deliberately NOT covered
  by the byte ceiling -- trusted tools stay uncapped by design; the fix is
  shaping at the producer.)
- **Web `max_chars` default (20000, ~5K tokens) is per-call only.** Fine for one
  fetch; unbounded across many. Relies on the model's restraint; revisit if web
  tools become heavily used in a single phase. The ceiling now bounds the
  pathological single-result case (20000 chars of CJK is ~80 KB of UTF-8).

---

## Reference

- Untrusted pre-emptive record cap: `koan/tools/builtin_tools.py`
  (`DEFAULT_LIMIT`, applied via the per-tool `limit` parameter)
- Byte budgets and ceiling: `koan/tools/byte_budget.py`
  (`DEFAULT_TOOL_RESULT_MAX_BYTES`, `TOOL_RESULT_CEILING_BYTES`,
  `ByteBudget`, `take_within_budget`, `ByteBudgetToolset`); the ceiling is
  installed around the builtin toolset in `koan/agents/pydantic_ai.py`
- Trusted tool cores: `koan/tools/koan_tools.py`
- How results accumulate in history: [token-streaming.md](./token-streaming.md),
  [state.md](./state.md) (the driver/LLM boundary owns `message_history`)

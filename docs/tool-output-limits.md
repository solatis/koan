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

So the invariant is: **every tool result MUST be bounded before it lands in
history.** The strategy question is not _whether_ to bound but _how_ -- and the
answer depends on who controls the producer.

---

## Trust classes

The bound koan applies depends on whether koan controls the content's size and
shape. This splits the tool vocabulary into two classes.

### Untrusted results -- reject on breach

Tools that surface content koan neither produces nor shapes: `read`, `grep`,
`glob`, `bash`. The size and structure are opaque -- koan cannot meaningfully
summarize arbitrary file bytes or command output, because it does not know what
in them matters to the caller.

**Rule:** enforce a content-agnostic hard ceiling _after_ producing the result;
on breach, **reject** with a narrowing hint. Never truncate-and-pass.

- Ceiling (`koan/tools/builtin_tools.py`, `_enforce_output_limits`):
  **> 500 lines OR >= 10 KB (UTF-8) -> error.** Conservative by default.
- **Why reject, not truncate:** a truncated prefix still deposits up to the
  ceiling on _every_ call, and a few of those compound straight back to the
  blowup. Worse, a partial result silently misleads the model into believing it
  saw the whole file.
- **Why rejection is safe here:** the model always has a narrowing lever --
  `read` with `offset`/`limit`, a tighter `grep` pattern or `glob`, a scoped
  `bash` (`head`, specific paths). The error names the limit and the levers, so
  it is actionable, not a dead end.
- **Ignored directories:** `glob` and `grep` additionally skip `_IGNORED_DIRS`
  (`.git`, `node_modules`, `__pycache__`, `.venv`, `.env`, `build`, `cache`),
  so a repo-root search is scoped to source files and does not trip the ceiling
  on dependency trees before the model even sees a result.

### Trusted results -- bound by construction

Tools koan implements end to end, returning a koan-defined schema:
`koan_search`, `koan_reflect`, `koan_memory_status`, `koan_artifact_list`, and
the control-ack tools (`koan_set_phase`, `koan_suggest_next`, ...).

`koan_artifact_read/write/edit` are also in this class. They are **trusted,
run-dir-scoped wrappers** over the built-in `read`/`write`/`edit`: koan authored
the run-dir artifact, so its content is bounded by construction and prompting.
`koan_artifact_read` calls `read_tool(..., enforce_limits=False)` -- it is
**exempt** from the untrusted reject ceiling. A large artifact is returned in
full; `offset`/`limit` are available for paging convenience but impose no hard
reject. See [tools.md](./tools.md).

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
through the reject ceiling -- the request parameter _is_ the bound.

---

## Invariants

1. **No tool result enters history unbounded.** Every result is either under an
   enforced ceiling, shaped to a bounded schema, or truncated to a
   caller-declared budget.
2. **Untrusted = reject; trusted = shape; never the reverse.** Do not truncate
   an untrusted result (it hides loss and still costs budget); do not reject a
   trusted result (the model cannot narrow it).
3. **Single source of truth for limits.** Untrusted ceilings live as named
   constants in `koan/tools/builtin_tools.py`
   (`_MAX_TOOL_OUTPUT_LINES`, `_MAX_TOOL_OUTPUT_BYTES`). Trusted caps live with
   their producer in `koan/tools/koan_tools.py`. No magic numbers scattered at
   call sites.
4. **Breaches are observable.** A rejection returns a visible error to the model
   (and the projection feed shows the tool_result). Trusted-side caps should
   note in the result when they elided content, so a debugged blowup can be
   traced to its source.
5. **Conservative by default.** Ceilings start low and are raised only with
   evidence. A too-tight ceiling costs an extra narrowing round-trip; a too-loose
   one costs the whole run.

---

## Known gaps (as of 2026-06-06)

The untrusted side is enforced (`_enforce_output_limits`). The trusted side is
**not yet uniformly bounded by construction** -- these are the open items:

- ~~The artifact reader had no bound and no pagination.~~ **Fixed:** now
  `koan_artifact_read`, a trusted wrapper that bypasses the untrusted ceiling
  (`enforce_limits=False`); `offset`/`limit` page for convenience with no hard
  reject. See [tools.md](./tools.md).
- **`koan_search` returns the full `body` of each of `k` entries.** `k` is
  bounded but per-entry `body` is not. Should field-bound `body` (first N chars +
  `entry_id`), so the count cap is also a size cap.
- **Web `max_chars` default (20000, ~5K tokens) is per-call only.** Fine for one
  fetch; unbounded across many. Relies on the model's restraint; revisit if web
  tools become heavily used in a single phase.

---

## Reference

- Untrusted ceiling + enforcement: `koan/tools/builtin_tools.py`
  (`_enforce_output_limits`, `_MAX_TOOL_OUTPUT_LINES`, `_MAX_TOOL_OUTPUT_BYTES`)
- Trusted tool cores: `koan/tools/koan_tools.py`
- How results accumulate in history: [token-streaming.md](./token-streaming.md),
  [state.md](./state.md) (the driver/LLM boundary owns `message_history`)

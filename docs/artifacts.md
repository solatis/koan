# Artifact lifecycle and persistence contract

Artifacts are markdown files that the orchestrator writes into the run directory
(`~/.koan/runs/<id>/`). They carry information between phases and, in some cases,
from phases to executor subagents. This document is the authoritative source of
truth for artifact lifetime, frontmatter shape, and the two write tools that
coexist between M1 and M5.

---

## Lifetime taxonomy

Artifacts fall into three lifetime classes:

**Frozen** -- written once, never re-written after the producing phase exits.
The content is stable for the remainder of the run. Downstream phases read it
but must not write it. Example: `brief.md` (produced by intake, read by all
subsequent phases and executor handoffs).

**Additive-forward** -- rewritten across the run, but outcome sections are
append-only once written. History stays visible in the file; earlier sections
are never deleted or overwritten. Example: `milestones.md` (created by
milestone-spec, updated by exec-review after each milestone completes).

**Disposable** -- written once by a producing phase, consumed by one or more
downstream phases, then superseded. Once the downstream work is done, the file
is no longer authoritative. Its content is compressed into a downstream artifact
(e.g., the completed milestone Outcome in `milestones.md`). Examples:
`plan.md`, `plan-milestone-N.md`.

---

## Per-artifact lifecycle table

| Artifact | Lifetime | Producer phase(s) | Reader phase(s) | Final-status timing |
| --- | --- | --- | --- | --- |
| `brief.md` | frozen | `intake` | `milestone-spec`, `milestone-review`, `plan-spec`, `plan-review`, `exec-review`, `curation`; executor (via handoff) | `Final` at intake exit |
| `milestones.md` | additive-forward | `milestone-spec` (CREATE), `exec-review` (UPDATE) | all milestone phases; executor (via handoff) | `In-Progress` until last milestone done; `Final` after last UPDATE |
| `plan.md` | disposable | `plan-spec` | `plan-review`, `execute`, `exec-review` | `Final` at plan-spec exit |
| `plan-milestone-N.md` | disposable | `plan-spec` | `plan-review`, `execute`, `exec-review` | `Final` at plan-spec exit |

Note: M2-M6 introduce the producers and readers listed in the table. M1 only
documents the contract; the tools that enforce it land in later milestones.

---

## Frontmatter convention

Every artifact written by `koan_artifact_write` or `koan_artifact_propose` has
a YAML frontmatter block prepended by the driver:

```
---
status: In-Progress
created: 2026-04-26T12:34:56.789012+00:00
last_modified: 2026-04-26T12:34:56.789012+00:00
---
```

Frontmatter rules:

- **Driver-managed, LLM-invisible.** The LLM never sees or writes frontmatter.
  `koan_artifact_view` strips it before returning the body to the caller.
  `koan_artifact_list` exposes `status` per file for frontend and projection use.
- **Fields**: `status` (string), `created` (ISO-8601 UTC), `last_modified`
  (ISO-8601 UTC). Field order is stable (`status`, `created`, `last_modified`).
- **First write**: `status` defaults to `In-Progress`; `created` and
  `last_modified` are both set to the write timestamp.
- **Subsequent writes**: `created` is preserved; `last_modified` is updated;
  `status` is preserved unless the caller passes an explicit value.
- **Migration**: artifacts written before M1 have no frontmatter. On the next
  write, frontmatter is attached; `created` is set to the migration timestamp
  (the original creation moment is unrecoverable).
- **Parse failure**: if an existing file has malformed frontmatter (no closing
  `---` delimiter or invalid YAML), the driver logs a warning, treats the file
  as having no frontmatter, and overwrites with valid frontmatter on the next
  write.

---

## Status taxonomy

Four values, defined in `koan/artifacts.py:STATUS_VALUES`:

| Status | Meaning |
| --- | --- |
| `Draft` | Work in progress; not ready for downstream consumption. |
| `In-Progress` | Default for first write. Active but not yet complete. |
| `Approved` | Reviewed and accepted; downstream phases may proceed. |
| `Final` | Producing phase has exited; content is stable. |

Precise per-artifact transition rules are settled in M4. M1 establishes the
vocabulary and the `In-Progress` default.

---

## Write tools

Two tools coexist between M1 and M5:

**`koan_artifact_propose(filename, content)`** -- legacy blocking tool.
Writes the file, emits `artifact_review_started`, and blocks until the user
submits a review through the UI. Returns the rendered review string. Use this
when the orchestrator must wait for human approval before proceeding.

**`koan_artifact_write(filename, content, status?)`** -- new non-blocking tool.
Writes the file and returns immediately with `{"ok": true, "filename": ...,
"status": ...}`. Emits `artifact_diff` events (sidebar refresh) but no review
events. Use this for programmatic writes where human approval is not required
at the write boundary.

Both tools share identical on-disk frontmatter shape. M5 deletes
`koan_artifact_propose` once all writers have migrated to `koan_artifact_write`.

# Koan Tools -- Strategy

Umbrella design document for koan's tool layer: how tools are classified, how
their results are formatted and bounded, and how edits are anchored. This is the
parent doc; sizing detail lives in its spoke.

> Spoke: [tool-output-limits.md](./tool-output-limits.md) -- result-size strategy
> (untrusted reject vs trusted bound-by-construction).

---

## Philosophy

A model's reasoning degrades as context grows, and every token re-sent on the
next request costs money and budget. So the tool layer optimises for **tight
context curation**: results are line-addressable (cheap to reference), bounded
(no single call blows the budget -- see the spoke), and edits target a precise
location without the model re-quoting large blocks.

Two ideas drive the design:

1. **Trust class decides the bound.** koan controls some producers and not
   others; the enforcement differs (see Taxonomy).
2. **Anchors decide the edit.** Reads hand back a stable per-line anchor; edits
   reference the anchor instead of an exact string match. This is the
   hash-anchored protocol below.

---

## Taxonomy: trusted vs untrusted

| Class          | Tools                              | koan controls...           | Bound strategy                    |
| -------------- | ---------------------------------- | -------------------------- | --------------------------------- |
| **Untrusted**  | `read`, `grep`, `glob`, `bash`     | nothing about the bytes    | reject on breach (hard ceiling)   |
| **Trusted**    | `koan_search`, `koan_reflect`, ... | producer + schema          | bound by construction (at source) |
| Web (sub-case) | `web_fetch`, `web_search`          | nothing; model sets budget | truncate to caller's `max_*`      |

The full reasoning and the enforced ceilings (currently > 500 lines OR >= 10 KB
for the untrusted class) live in [tool-output-limits.md](./tool-output-limits.md).

### Scoped wrappers (`koan_artifact_read/write/edit`)

The artifact tools are **thin, run-dir-scoped wrappers** over the built-in
`read`/`write`/`edit` (`koan/tools/koan_tools.py` -> `koan/tools/builtin_tools.py`).
They exist to _limit_ file access: a planning role (e.g. the orchestrator) gets
artifact read/write/edit confined to its run directory's artifacts, but not raw
`write`/`edit` on arbitrary project files. Each wrapper adds only filename
validation, run-dir containment, and (for write/edit) the `artifact_diff`
projection event.

`koan_artifact_read` is **trusted and exempt** from the untrusted reject ceiling.
It calls `read_tool(..., enforce_limits=False)` -- artifacts are koan-authored
run-dir content, bounded by prompting, so they are known-size by construction.
`offset`/`limit` are available for paging convenience, but there is **no hard
reject**: a large artifact is returned in full. `koan_artifact_write`/`edit`
similarly bypass the ceiling; artifacts are plain markdown with no frontmatter.

---

## Output format conventions

Every result that addresses file content is **line-addressable**: the reader can
point at a specific line without re-reading. Formats are stable so the metrics
parsers (`koan/agents/pydantic_ai.py`) and the anchor protocol can rely on them.

### `read` / `koan_artifact_read`

A line number prefix on **every** line, always:

```
{lineno}\t{anchor}§{content}
```

- `{lineno}` -- 1-based absolute line number (honours `offset`), tab-separated.
  Always present, even for a one-line slice. Keeps read output greppable and
  lets a human cross-reference.
- `{anchor}§{content}` -- the hash anchor and the verbatim line (see Anchors).
  `§` (U+00A7) is the anchor delimiter; it never appears in an anchor.

Example:

```
12	a1f3c2d8§def process(data):
13	5e9b0011§    return data + 1
14	0042ab90§
```

The anchor column is what makes a line editable -- see Hash-anchored edits.

### `grep`

```
{filepath}:{lineno}:{content}
```

Already implemented. grep is a **find** tool, not an **edit** tool: its results
span many files and partial lines, so they do **not** carry anchors. To edit a
location grep found, the model reads it first (which mints the anchor).

### `glob` / `bash`

`glob` -> `Found N files` header + one path per line. `bash` -> combined
stdout/stderr, exit-code prefixed on failure. Neither is line-addressable for
editing; both are subject to the untrusted ceiling.

`glob` and `grep` additionally skip ignored directories (`_IGNORED_DIRS` in
`koan/tools/builtin_tools.py`: `.git`, `node_modules`, `__pycache__`, `.venv`,
`.env`, `build`, `cache`) so a repo-root search is scoped to source and does
not trip the reject ceiling on dependency trees.

---

## Hash-anchored edits

> Status: **implemented** in `koan/tools/line_anchors.py`. Adapted from
> [dirac](https://github.com/dirac-run/dirac)'s hash-anchored edit protocol.

### The problem with exact-string-match

Exact-string-match editing (`old_string` / `new_string`, single unique
occurrence) -- which koan used before this protocol -- is fragile and
token-heavy:

- **Ambiguity.** A line like `}` or `return None` occurs many times; the model
  must quote a large surrounding block to make `old_string` unique. That block
  is pure context overhead.
- **Drift.** If the file changed since the read, the match silently lands in the
  wrong place or fails with no hint to re-read.
- **Cost.** Re-quoting context to disambiguate is exactly the token bloat the
  tool layer is trying to avoid.

### The anchor protocol

Each line gets a short, content-derived **anchor**. The read hands anchors back;
the edit references them.

**Anchor derivation (stateless, deterministic):**

- `anchor = fnv1a32(line_content)` rendered as an 8-char hex string, where
  `line_content` is the exact line **including indentation, excluding the
  trailing newline**. FNV-1a 32-bit -- fast, dependency-free, matches dirac.
- **Disambiguation:** when two or more lines in the file hash identically (blank
  lines, repeated `}`), they get a 1-based ordinal suffix in file order:
  `0042ab90`, `0042ab90~2`, `0042ab90~3`. A unique line carries the bare hash.

Stateless on purpose: anchors are recomputed from the file on disk at edit time,
not stored in task state. (dirac keeps a stateful anchor map for stability
across un-re-read edits; koan instead resolves a whole edit batch against one
on-disk snapshot -- see Resolution -- which gives the same guarantee without the
state. This fits koan's stateless-algorithm preference.)

**The read hands back the anchor inline:** `a1f3c2d8§def process(data):`. The
model copies that token verbatim into an edit. The token carries **both** the
location (`a1f3c2d8`) and the verification content (`def process(data):`).

### The edit signature

`edit` and `koan_artifact_edit` are anchor-only (the string mode was removed):

```
edit(
  file_path,
  anchor:     "a1f3c2d8§def process(data):",   # location + verification, copied from read
  text:       "def process(data, *, strict):", # replacement / inserted content
  end_anchor: "5e9b0011§    return data + 1",   # optional; for multi-line replace ranges
  edit_type:  "replace",                        # replace | insert_before | insert_after
)
```

- `replace` with no `end_anchor` replaces the single anchored line.
- `replace` with `end_anchor` replaces the inclusive range `[anchor, end_anchor]`.
- `insert_before` / `insert_after` insert `text` relative to `anchor`; no
  `end_anchor`.
- Empty `text` on a `replace` deletes the target line(s).

### Resolution and verification

For each edit, against the file's **current** on-disk content:

1. Parse `anchor` into `(hash, ordinal, provided_content)` (split on `§`).
2. Recompute line anchors for the whole file; find the line whose anchor matches
   `hash` (+ ordinal). Not found -> error: _"anchor not found; re-read the file
   for current anchors."_
3. Verify `provided_content == actual_line`. Mismatch -> error showing
   expected vs provided (the file drifted since the read).
4. On a batch, resolve **all** anchors against the snapshot first, then apply in
   **descending line order** so earlier edits don't invalidate later indices.

This is dirac's `resolveAnchor` + reverse-apply, adapted. Steps 2-3 give precise
location _and_ staleness detection; step 4 makes multi-edit batches safe without
stateful anchors.

### Scope

The protocol is shared by the raw tools and the scoped artifact wrappers:

| Tool                           | Reads anchors via    | Edits via            |
| ------------------------------ | -------------------- | -------------------- |
| `read` (untrusted)             | `read`               | `edit`               |
| `koan_artifact_read` (wrapper) | `koan_artifact_read` | `koan_artifact_edit` |

Because `koan_artifact_read/edit` simply delegate to `read`/`edit`, anchors
mint and resolve identically; the wrapper only scopes the path to run_dir.
`koan_artifact_read` takes `offset`/`limit` like `read`.

### Decisions (resolved)

1. **Anchor scheme:** stateless content-hash + `~N` ordinal. Anchors are
   recomputed from the file at edit time; no per-task anchor store. (dirac's
   stateful word-anchors were the alternative; the stateless scheme fits koan's
   stateless-algorithm preference.)
2. **Cutover:** string mode (`old_string`/`new_string`) was **removed
   outright**; `edit` and `koan_artifact_edit` are anchor-only and the tests were
   migrated in one pass.
3. **Anchor output:** **always** emitted -- every `read` / `koan_artifact_read`
   line carries its anchor, so an edit is always possible without a re-read.

> Single-call batches: today each `edit` / `koan_artifact_edit` applies one edit.
> The resolve-all-then-reverse-apply design in `apply_anchored_edit` already
> supports multi-edit batches against one snapshot; exposing a batch parameter is
> a future extension, not a redesign.

---

## Reference

- Anchor protocol: `koan/tools/line_anchors.py`
  (`fnv1a32`, `compute_anchors`, `render_anchored`, `apply_anchored_edit`)
- Untrusted enforcement + read/edit: `koan/tools/builtin_tools.py`
- Trusted tool cores (artifact read/write/edit): `koan/tools/koan_tools.py`
- Sizing strategy: [tool-output-limits.md](./tool-output-limits.md)
- Inspiration: [dirac](https://github.com/dirac-run/dirac) -- `src/utils/line-hashing.ts`,
  `src/core/task/tools/modules/edit_file/utils/EditExecutor.ts`

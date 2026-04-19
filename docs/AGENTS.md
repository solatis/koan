# docs/ Conventions

Conventions for agents writing or editing files in this directory.

---

## No temporal contamination

Documentation describes the current state of the system as if it has always
been this way. It is not a changelog.

**Forbidden patterns:**

| Pattern | Example violation | Fix |
|---|---|---|
| "replaces X" (historical) | "This replaces the old polling design" | Describe what the system does |
| "previously" | "Previously, events were cached in a dict" | Delete — describe current state only |
| "the old X" | "the old model's problem was..." | Describe the design principle instead |
| "used to" | "scouts used to be top-level phases" | Delete or restructure |
| "was changed from" | "the event was renamed from pipeline-end" | Delete |
| "we switched to" | "we switched to asyncio.Future" | Delete |
| "ported from" | "ported verbatim from the old CSS" | Delete |
| "formerly" | "formerly called pipeline-end" | Delete |

**Permitted uses of "replaces":**

"Replaces" describing a logical operation on data is fine — it is not temporal:

- ✓ `applySnapshot` atomically replaces store state
- ✓ `artifacts_changed` sets the `artifacts` list wholesale
- ✗ "The projection system replaces the ad-hoc dict" (historical)

**Plans are exempt.** Files under `plans/` are inherently temporal — they
document what to change and why. The rule applies only to `docs/`, code
comments, and docstrings.

**Design decisions mentioning rejected alternatives are fine.** A comment
explaining "X was considered but Y is used because Z" documents a design
choice. The framing must be about the decision rationale, not a migration
narrative:

- ✓ "`python-eventsourcing` was considered but is designed for database persistence, not in-memory UI state"
- ✗ "We tried `python-eventsourcing` but switched to a custom implementation"

---

## Spoke document structure

Spoke documents cover a subsystem in depth. Every spoke document follows this
structure:

```markdown
# Title

One sentence: what this document covers.

> Parent doc: [architecture.md](./architecture.md)

---

## Overview

One paragraph: the problem this subsystem solves and the high-level approach.

**Key invariant (if any):** Bold sentence capturing the non-negotiable rule.

---

## [Concept sections]

Technical detail organized by concept, not by implementation order.

---

## Design Decisions

Named subsections, one per decision. Each captures:
- The choice made
- Why (first-principles rationale, not migration history)
- Alternatives considered and why they were not chosen
```

**Formatting conventions:**

- Section separators: `---` on its own line
- Parent doc reference: `> Parent doc: [name](./path.md)` immediately after
  the opening description, before the first `---`
- Tables: GFM pipe tables with `|---|---|` separator row
- Code blocks: fenced with language tag (` ```python `, ` ```typescript `, etc.)
- Cross-references: `[section-name](./file.md#anchor)` using lowercase-hyphenated anchors
- Bold for key terms on first use: `**design invariant**`, `**materialized projection**`

---

## Full documentation conventions

For invisible knowledge, README vs CLAUDE.md, in-code documentation tiers,
and module documentation standards, see:

[resources/conventions/documentation.md](../resources/conventions/documentation.md)

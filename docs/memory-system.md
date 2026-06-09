# Koan Memory System — Specification v4

## Overview

Koan's memory system captures project knowledge that is not derivable
from code. It prevents LLM agents from repeating mistakes, re-deriving
settled questions, and drifting from established architectural choices
across workflow runs.

The memory system consists of markdown files stored in `.koan/memory/`
within the project repository. These files are version-controlled
alongside the project's source code, human-readable, and maintained
by koan's LLM agents with explicit user review. A retrieval layer
indexes these files and provides hybrid search (semantic + keyword)
for koan's agents to query during workflows.

Every memory entry is a single markdown file with YAML frontmatter
carrying structured metadata and a prose body written in event-style.
This design makes each entry independently retrievable, independently
reviewable, and independently trackable via version control.

### What this is not

This is not conversational memory. Systems like Mem0, SimpleMem,
Hindsight, and A-Mem extract and consolidate facts from dialogue
streams. Their benchmarks (LoCoMo, LongMemEval) test recall of
conversational facts across sessions.

Koan's memory is fundamentally different:

- **Deliberate, not extracted.** Entries are proposed by the
  orchestrator agent and approved by the human user during a
  curation workflow. Every entry is human-reviewed before it enters
  memory.

- **Structured, not atomic.** Each entry is a self-contained unit
  carrying the knowledge its type requires — an architectural
  decision with rationale and alternatives, not an atomic fact like
  "user prefers coffee." The grain size is justified by EMem's
  neo-Davidsonian argument: relational knowledge must stay bundled
  (Zhou et al., 2025).

- **The producer and consumer are LLMs.** The primary reader of
  memory entries is the intake agent at the start of the next
  workflow. The human oversees (reviews proposals, approves entries)
  but does not browse or query memory directly. Design decisions
  optimize for LLM consumption, not human browsability.

- **Write-infrequent, read-frequent.** Memory is written during
  curation (end of workflow or on-demand review). It is read at
  the start of every workflow. The read path matters more than
  the write path.

---

## Entry format

Each memory entry is a standalone markdown file consisting of two
parts: YAML frontmatter and a prose body.

### YAML frontmatter

Structured metadata that enables filtering and freshness tracking.

```yaml
---
title: PostgreSQL for Auth Service
type: decision
created: 2026-04-10T14:23:00Z
modified: 2026-04-10T14:23:00Z
related: [0002-infrastructure.md]
---
```

Required fields:

- **title**: Short descriptive name, used in listings and the project
  summary
- **type**: One of `decision`, `context`, `lesson`, `procedure`
- **created**: ISO 8601 timestamp, set automatically when the entry
  is first written. Never modified after creation.
- **modified**: ISO 8601 timestamp, updated automatically on every
  write. Enables freshness tracking and staleness detection.

Optional fields:

- **related**: Filenames of related entries (e.g.,
  `0002-infrastructure.md`). Explicit structural connections — a
  lesson linking to its derived procedure, a decision linking to the
  context that motivated it. These serve as signals for curation
  health checks.

A file's presence is its status. If a file exists in `.koan/memory/`,
it is active knowledge. The `koan_forget` tool deletes the file.
Git preserves the history of anything removed.

### Title writing

Titles participate in the embedding text
(`# {title}\ntype: {type}\n\n{body}` in
`koan/memory/retrieval/index.py`). They are not just labels — they
are the sharpest single line of the entry and carry embedding signal
alongside the body.

Titles read as factual headlines that name the specific decision,
lesson, procedure, or context fact. They name a subsystem and a
claim in one line, not just the topic.

Good titles:

- "PostgreSQL 16.2 chosen over SQLite for auth service due to
  concurrent-write load"
- "AGENTS.md describing functions that do not yet exist creates
  implicit pressure on executors"
- "All state file writes use atomic tmp-file + os.rename()"

Bad titles:

- "Memory system" — topic without a claim
- "PostgreSQL decision" — vague, no claim
- "Curation phase improvements" — vague, no specifics

No length cap. Titles are as long as the claim requires.

### Prose body

Everything after the frontmatter is the prose body, written
following the writing discipline described below.

**The entry must be retrievable without external state.** This
follows Anthropic's contextual retrieval technique, which
demonstrated a 35% reduction in retrieval failures when contextual
information is present in the embedded chunk. Because the entire
file is embedded as a single chunk for retrieval, the body should
contain enough specific context — named subsystems, file paths,
decision names — that the embedding has anchor signal and the entry
is interpretable standalone. How this is achieved (a situating
opening, a sharp title, concrete naming throughout the body) is the
writer's choice. Vague openings without specific entities
("This system...", "The project...") hurt retrieval.

### Complete example

```markdown
---
title: PostgreSQL for Auth Service
type: decision
created: 2026-04-10T14:23:00Z
modified: 2026-04-10T14:23:00Z
related: [0002-infrastructure.md]
---

TrapperKeeper auth service -- user decided to migrate from SQLite to
PostgreSQL 16.2 on 2026-04-10. Rationale: SQLite could not handle
concurrent write loads from the new worker pool (>50 connections).
Alternatives rejected: SQLite WAL mode (single-writer limitation),
CockroachDB (operational complexity too high for a two-person team).
Decision surfaced during intake when user described timeout errors
under load.
```

---

## Writing discipline

Memory entries follow a writing discipline organized around what
content each type must carry. The EMem paper (Zhou et al., 2025,
"A Simple Yet Strong Baseline for Long-Term Conversational Memory
of LLM Agents") grounds the structure in neo-Davidsonian event
semantics: treating events as single units with multiple arguments
outperforms decomposing them into relation triples. This argument
applies most forcefully to decisions, where rationale, rejected
alternatives, and surfacing context must stay bundled to preserve
the knowledge's coherence.

Temporal context lives in the entry's frontmatter `created` and
`modified` fields, which `koan/memory/writer.py` populates
automatically. Prose dates may appear when a specific date is itself
part of the rationale or anchors a load-bearing fact (e.g., "the
migration on 2026-04-10 failed because..."), but embedding a date
in every claim is not required.

### Rules

1. **Situate for retrieval.** The entry should contain enough
   specific context — named subsystems, file paths, decision names —
   that the embedding has anchor signal and the entry is interpretable
   standalone. A sharp title, concrete entity names in the body, or
   both achieve this. Vague openings without specific entities
   ("This system...", "The project...") hurt retrieval.

2. **Attribute when it affects trust calibration.** User-stated facts
   carry higher trust than LLM-inferred facts; name the source when
   the distinction matters. Anonymous attribution ("it was decided")
   still fails for decisions. Background facts, lessons, and
   procedures may carry no attribution and should read as standalone
   knowledge.

3. **No forward-looking language.** Entries record what has happened
   or what is observed, not plans for the future. Rationale that
   something "should" or "must" be done belongs inside a past-tense
   framing of the decision that established the rule.

4. **Name things concretely.** Not "the database" but "PostgreSQL 16.2"
   or "the auth service's primary data store."

5. **Each entry must stand alone.** Interpretable without any other
   file, true regardless of when it is read.

### Examples

Bad — relative, will become stale:

> We use PostgreSQL for the auth service.

Good — concrete naming, rationale, rejected alternatives, standalone:

> The auth service in TrapperKeeper uses PostgreSQL 16.2 as its
> primary data store. Chosen over SQLite because concurrent write
> loads from the worker pool (>50 connections) exceeded SQLite's
> single-writer limit. Alternatives rejected: SQLite WAL mode
> (single-writer limitation persists), CockroachDB (operational
> complexity too high for a two-person team). Decision surfaced
> during intake when user described timeout errors under load.

---

## Per-type writing guidelines

Each memory type has a characteristic content shape. Length follows
the content the entry must carry; there is no token target. The four
types are defined in the section below; this section describes how
each is written.

### Decision

A decision entry must carry: the choice, the rationale (why this
over alternatives), the rejected alternatives and why they failed,
and the surfacing context (how the decision came up). These elements
must stay bundled — splitting rationale and rejected alternatives
into separate entries destroys the coherence of the knowledge.

Shape: `[Subsystem] -- [actor] decided [choice]. Rationale: [why].
Alternatives rejected: [list with reasons]. Decision surfaced [when
and how].`

Example:

> TrapperKeeper auth service -- user decided to migrate from SQLite
> to PostgreSQL 16.2. Rationale: concurrent write loads from the
> worker pool (>50 connections) exceeded SQLite's single-writer
> capacity. Alternatives rejected: SQLite WAL mode (single-writer
> limitation persists under high connection counts), CockroachDB
> (operational complexity too high for a two-person team). Decision
> surfaced during intake when user described timeout errors under
> load.

### Context

A context entry must carry: the specific stable fact (with concrete
entity names) and one sentence on why it matters for future agents.

Shape: `[Subsystem / project area] -- [specific fact with concrete
names]. This matters because [consequence for agents].`

Example:

> TrapperKeeper deployment -- secrets are managed via `.env` files
> loaded by docker-compose; they must never appear in
> `docker-compose.yml` or version control. This matters because
> executors writing docker-compose changes may inadvertently inline
> secrets if unaware of this constraint.

### Lesson

A lesson entry must carry: what happened (the concrete event), the
root cause (not symptoms), and the prevention rule or procedure that
follows.

Shape: `[Subsystem] -- [what happened]. Root cause: [why].
Prevention: [rule or procedure to prevent recurrence, or "see
procedure NNNN" if a paired procedure exists].`

Example:

> User-management service deployment -- a feature branch added a
> `last_seen_at` column to the ORM model but omitted the Alembic
> migration. Local tests passed because the local test database was
> SQLite, which auto-creates columns from ORM definitions. Staging
> deployment failed when PostgreSQL rejected inserts for the missing
> column. Root cause: test harness used a different database engine
> than production, hiding schema drift at merge time. Prevention:
> run all Alembic migrations against an empty PostgreSQL instance in
> CI before test suites execute.

### Procedure

A procedure entry must carry: the triggering condition, the rule or
action, and (where useful) the consequence of violating it. This is
the type closest to a sharp factual rule — trigger condition,
mechanism, consequence, and (where relevant) the counter-frame
showing what the wrong approach looks like.

Shape: `[Subsystem] -- when [trigger condition], [action / rule].
Violating this leads to [consequence].`

Example:

> CI pipeline -- before any database migration lands in a branch,
> run all pending Alembic migrations against an empty PostgreSQL
> instance as a CI step. The wrong approach is relying on
> ORM-level auto-migration or local test databases that diverge
> from the production engine. Violating this leads to schema drift
> that passes local tests and fails on staging or production.

---

## Memory types

Koan classifies memories into four types. The type field is metadata
for filtering and curation heuristics — it does not determine where
the file is stored. All entries live in a single flat directory.

### Decisions — _Why is the project the way it is?_

The most critical memory type. Decisions capture **why** the project
is the way it is — not just what was chosen, but what was rejected
and why.

Each decision entry should capture, where known: what was decided,
the rationale (constraints that drove the choice), alternatives
considered and rejected, and how the decision surfaced (intake,
mid-workflow correction, post-mortem).

Decisions include both explicit choices (user-stated) and implicit
choices (LLM-inferred from user behavior). Implicit decisions
should be clearly attributed as inferred in the prose body.

### Context — _What do I need to know that isn't in the code?_

Objective facts about the project, team, domain, and infrastructure
that are not derivable from the codebase and are expected to remain
stable across sessions. Team size, deployment setup, external
dependencies, business constraints.

### Lessons — _What went wrong before?_

Mistakes made during workflows and the corrections applied. Each
entry captures: what happened, what the user did to correct it,
root cause, and what should change to prevent recurrence.

A lesson often produces a new decision or procedure, but the lesson
itself is the error record — the ground truth about what went wrong.

### Procedures — _How should I approach things in this project?_

Patterns, strategies, and behavioral rules that emerged from
experience. Procedures capture actionable "how-to" knowledge that
tells agents what to do, not just what happened or what was decided.

The distinction from lessons: a lesson says "executor generated unit
tests despite policy." A procedure says "always verify testing policy
before any code generation task." The lesson is the event record; the
procedure is the actionable rule.

Procedures emerge from three sources: lessons that generalize into
prevention rules, positive patterns observed after successful
workflows, and the memory review workflow surfacing recurring themes.

---

## File organization

```
.koan/
  memory/
    summary.md                          # project orientation briefing
    0001-postgresql-for-auth.md         # individual entries
    0002-infrastructure.md
    0003-no-unit-tests.md
    0004-redis-session-management.md
    0005-unit-test-generation-lesson.md
    0006-testing-policy-check.md
    0007-database-migration-steps.md
    0008-team-structure.md
    0009-auth0-integration.md
```

All entries live in a single flat directory. The type of each entry
is recorded in its YAML frontmatter, not in the directory structure.
This keeps topically related entries together on disk — the decision
about PostgreSQL, the infrastructure context it relates to, and the
lesson about PostgreSQL migrations are all neighbors in the directory,
not scattered across subdirectories.

Every hierarchical memory system in the literature groups entries by
**semantic/topical similarity**, not by cognitive type (Talebirad et
al., ICLR 2026; Hu et al., 2026; Sun & Zeng, 2025). Type-based
partitioning separates related knowledge that agents need together.
Koan follows this principle: the flat store is the topic-neutral
starting point, and if the knowledge base grows to the point where
flat retrieval degrades, the scaling path is topic-based clustering
(not type-based subdirectories).

### Project summary

`summary.md` is a synthesized project orientation briefing,
regenerated after each workflow completes. Unlike memory entries, it
is a derived artifact — produced by reading all entries and
synthesizing them into a concise overview. It does not have the
standard entry format (no sequential number, no frontmatter).

The summary is the first thing an LLM reads when starting any
workflow. It is loaded in full at intake (not retrieved via search)
and should stay within ~2000 tokens.

The summary is regenerated by reading all entries directly. At the
current scale (tens to low hundreds of entries), this fits within a
single LLM call. When the knowledge base grows to the point where
all entries no longer fit in a cheap model's context window, that
threshold is the signal to introduce topic-based clustering —
grouping entries by semantic similarity and generating per-topic
summaries. Until then, the flat structure with a single summary is
the simpler and sufficient design.

### Naming convention

Files are named `NNNN-short-description.md` where `NNNN` is a
zero-padded sequential number. The number provides stable ordering
and prevents filename collisions. The description is a human-readable
slug derived from the title.

New entries are assigned the next available number. Numbers are never
reused — if entry `0005` is deleted, the next entry is still the
next number after the current highest.

### Version control

The `.koan/memory/` directory is checked into version control
alongside the project's source code. Memory changes appear in diffs,
can be reviewed in pull requests, and have full git history.

---

## Memory lifecycle

Memory is created and maintained through a single mechanism —
**curation** — invoked with different sources and directives
depending on the context. All memory modifications require explicit
user review.

### The curation workflow

Curation is an iterative workflow that processes source material
in batches, classifying each candidate against existing memory
before proposing changes. This write-time classification follows
the pattern established by Mem0's memory management algorithm:
every candidate knowledge item is classified (ADD, UPDATE, NOOP,
DEPRECATE) before being committed, preventing duplicate and
redundant entries.

The curation workflow has three steps:

**Step 1: Orient.** Quick orientation in existing memory and source
material. Read the project summary to understand what's already
captured. Survey the scope of the source material based on the
directive. Do not produce proposals yet.

**Step 2: Curate.** The main iterative loop. Process knowledge in
batches of 3–5 candidates. For each batch:

1. Identify 3–5 candidate knowledge items from the source
2. Classify each candidate against existing memory:
   - **ADD**: No existing entry covers this → draft a new entry
   - **UPDATE**: An existing entry covers this but needs revision
     → draft an update to the existing entry
   - **NOOP**: An existing entry already captures this → skip
   - **DEPRECATE**: This knowledge makes an existing entry obsolete
     → propose deprecation
3. Draft complete entry proposals for ADD and UPDATE candidates
4. Present the batch to the user for review
5. Apply approved changes (via `koan_memorize` and `koan_forget`)
6. Reassess: is there more to extract? After the obvious, look for
   implications, connections, conventions, edge cases. Continue
   the loop with a new batch if so.

The loop converges when successive batches produce mostly NOOPs,
the source material is exhausted, or the user says to stop.

**Step 3: Finalize.** Report what was done. Summary regeneration
happens automatically — the next call to `koan_memory_status` will
detect a stale summary and regenerate it just-in-time.

### Duplicate detection during curation

During the curate step, the orchestrator must check whether a
candidate duplicates or overlaps with an existing entry. Without a
retrieval index available during early milestones, the orchestrator
relies on two mechanisms:

1. **Summary orientation.** The project summary provides a compressed
   view of all captured knowledge. If a candidate covers something
   already mentioned in the summary, the orchestrator can classify
   it as NOOP or UPDATE rather than ADD.

2. **Direct file reading.** The orchestrator has native filesystem
   access and can read any entry in `.koan/memory/`. When a
   candidate is close to an existing topic, the orchestrator reads
   the potentially overlapping entries and compares before
   classifying.

Once the retrieval index is available (Milestone 3+), the curation
step can use `koan_search` to find related entries before
classifying, making duplicate detection more reliable.

### Memory operation tools

The orchestrator interacts with memory through three in-process tools.
Individual entry reading uses the orchestrator's native filesystem
access (the entries are plain markdown).

**`koan_memorize`** — Write a memory entry. When called without an
entry identifier, creates a new entry with automatic sequence
numbering, filename slug generation, and timestamps. When called
with an entry identifier, updates the existing entry in-place. The
`created` timestamp is set once on creation; `modified` is updated
on every write. Returns the file path and operation performed.

**`koan_forget`** — Remove an entry from active memory. Deletes the
file from disk. Git preserves the history of removed entries. The
entry disappears from the summary and retrieval immediately.

**`koan_memory_status`** — Orientation tool. Returns the project
summary and a listing of all entries (title, sequence number, type,
created/modified dates). Before returning, checks whether the
summary is stale (by comparing the summary's generation timestamp
against the most recent entry modification) and regenerates it
just-in-time using a cheap-tier model.

### Curation directives

The same workflow serves all memory operations through different
directives:

**Post-mortem** runs at the end of every koan workflow. Source: the
workflow transcript already in the orchestrator's context window.
Focus: decisions made, lessons learned, procedures established,
context surfaced. No scouts — everything is already known.

**Review** is triggered on-demand. Source: the existing memory
corpus. Focus: assess health — staleness, contradictions, gaps,
entries that should be merged, lessons lacking procedures. May
dispatch scouts to verify decisions against the current codebase.
If memory is empty, pivots to bootstrap (explore codebase,
interview user). If the user's task description references source
material, pivots to document ingestion.

**Document** ingests specific source material the user provides.
Source: architecture docs, specs, codebase files. May dispatch
scouts for large sources. Bootstrap is document curation at broad
scope — there is no separate bootstrap directive.

### Triggering curation

Curation is triggered:

- **Automatically** at the end of every koan workflow (post-mortem
  directive).
- **On explicit user request** (review or document directive).
- **On suggestion** after N completed workflows, koan suggests a
  review curation. Configurable, e.g. every 5 workflows.

### Model tier assignments

Curation runs within the **orchestrator's context** (strong-tier
model). The orchestrator handles all judgment — what to capture,
how to phrase it, whether existing entries need updating. No
separate curation subagent is spawned.

Summary regeneration (inside `koan_memory_status`) uses a
**cheap-tier model**. This is a mechanical operation — condensing
existing entries into a prose overview.

The `koan_reflect` tool uses a **mid-tier model** (Gemini Flash,
configurable via `KOAN_REFLECT_MODEL`) via **pydantic-ai** with the
`google-gla` provider. Summary regeneration uses the same pydantic-ai
path with the cheap-tier model (configurable via `KOAN_LLM_MODEL`,
default `gemini-flash-lite-latest`). Both subsystems read `GEMINI_API_KEY`
or `GOOGLE_API_KEY` from the environment.

Reflect runs a multi-turn tool-calling loop in which a single LLM
conversation plans queries, interprets results, judges sufficiency, and
synthesizes the briefing. Thinking and text deltas are streamed as
`reflect_trace` events (with `kind: "thinking"` or `kind: "text"`) so
the frontend receives interleaved reasoning alongside search rows.
These tasks sit squarely in the regime that modern mid-tier models
handle well -- planning a handful of decomposed searches, reading
structured results, writing a bounded briefing -- and a Pro-class
model is overkill for the latency cost. Cheap-tier models (flash-lite
and below) degrade sharply here: they echo the user's question as a
single query, produce malformed tool calls, and give up early.
Mid-tier is the sweet spot; reflect runs infrequently (only on
explicit invocation) so the per-call cost is acceptable.

### Direct human editing

Because memory files are plain markdown in version control, humans
can edit them directly at any time — in their editor, via a pull
request, or through any other workflow. The sync layer detects
changes and re-indexes modified files. The `modified` timestamp
in frontmatter should be updated when humans edit entries; the
next `koan_memory_status` call will detect the stale summary.

---

## Retrieval

Koan builds its own retrieval layer over the memory files rather
than delegating to a conversational memory system. This is because
koan's memory entries are already well-structured, self-contained
documents — running them through a fact extraction pipeline (as
systems like Hindsight do) would be destructive, stripping the
framing and rationale that make entries valuable.

### Entry grain size

An entry is large enough to carry the content its type requires.
The grain follows the content; there is no token target.

**The neo-Davidsonian argument (Zhou et al., EMem 2025).** For
decisions, this means bundling the choice, rationale, rejected
alternatives, and surfacing context as one entry. When knowledge is
relational — when the value lies in connections between elements —
atomizing it into independent facts destroys the structure that
makes it useful. If a decision ("chose PostgreSQL over SQLite due to
concurrency, rejecting CockroachDB for operational complexity") is
split into three separate atomic facts, a query about CockroachDB
retrieves the CockroachDB fact but loses the decision context. The
retriever would need to find all three facts and the LLM would need
to reassemble them, requiring multi-hop reasoning at query time —
the operation that degrades performance most across all benchmarks.

**Per-type grain.** For lessons, procedures, and context entries,
the grain is the natural size of the knowledge: a lesson carries
event + root cause + prevention; a procedure carries trigger + rule

- consequence; a context entry carries the stable fact and why it
  matters. These are typically tighter than decisions because the
  structure is simpler.

The grain must keep the relations within each entry intact. Entries
that omit rationale, root cause, or triggering conditions lose the
value that makes them worth retrieving. Retrieving 3–5 entries at
natural grain size fits within a reasonable context budget for most
knowledge bases.

### Indexing

The sync layer watches `.koan/memory/` and indexes each individual
entry file as a single chunk. Because entries are written to be self-contained, most entries can
be embedded whole without further chunking.

For each entry, the sync layer:

1. Reads the file content (frontmatter + prose body)
2. Parses the YAML frontmatter into structured metadata
3. Computes a content hash for change detection
4. Generates a dense embedding of the full text
5. Indexes the text for BM25 keyword search
6. Stores the embedding, BM25 index entry, and metadata

`summary.md` is NOT indexed. It is loaded mechanically at intake
and accessed directly by tools — it does not need search to find.

Re-indexing is triggered when a file's content hash changes.

### Two retrieval mechanisms

Koan provides two retrieval mechanisms that solve fundamentally
different problems: **mechanical context injection** (automatic,
at phase boundaries) and **agent-invoked tools** (on-demand,
during reasoning). The distinction is not about pipeline
mechanics — both use the same hybrid search infrastructure. The
distinction is about what each mechanism can catch.

The "Memory in the Age of AI Agents" survey (2026) identifies
the core risk of relying on agent-initiated retrieval: "When an
agent overestimates its internal knowledge and fails to initiate
retrieval when needed, the system can fall into a silent failure
mode in which knowledge gaps may lead to hallucinated outputs."
This failure mode defines the boundary between the two mechanisms.

**Agent-invoked tools handle known unknowns.** The agent is
reasoning, recognizes a gap in its knowledge, and formulates a
targeted query. "What's the session management architecture?"
or "What constraints apply to database migrations?" The agent
is aware of its own gap and goes looking. This works when the
agent has enough context to know _what_ it doesn't know.

**Mechanical injection handles unknown unknowns.** The agent
doesn't know that a testing policy exists. It doesn't know that
a previous executor hardcoded credentials and a lesson was
captured about it. It cannot search for something it doesn't
know to search for. Mechanical injection is the system's
guarantee that relevant knowledge surfaces regardless of
whether the agent thinks to look. It operates without the
agent's involvement, driven by the workflow structure rather
than by agent reasoning.

#### Mechanical context injection

Mechanical injection runs at phase boundaries — points in the
workflow where the problem domain shifts and different knowledge
becomes relevant. Each workflow phase may optionally request
memory injection by providing a **retrieval directive**: a static,
human-authored sentence describing what kind of knowledge is
most likely to matter for the phase.

The injection pipeline has four steps:

**Step 1: Generate search queries.** A cheap-tier model receives
two inputs and produces 1-3 search queries:

The first input is the **retrieval directive** from the phase
definition. This is a static sentence written by the workflow
designer that describes the retrieval intent for the phase --
what kind of knowledge typically matters. For example, an
execution phase might carry the directive "procedures,
conventions, and past lessons related to the subsystem being
modified." A verification phase might carry "quality policies,
testing conventions, and known pitfalls." The directive
provides the _what to look for_ dimension.

The second input is **recent artifacts and context** that provide
the _where to look_ dimension -- the topical anchor. The anchor
is composed from: the task description, then all `.md` files in
the run directory sorted by mtime ascending (chronological order
puts the most recent artifact last, where attention is strongest;
`brief.md` written by intake serves as the de facto initiative
anchor). The cheap model combines topic (from the
artifacts/context) with intent (from the directive) to produce
well-formed queries.

Example: the execution phase has directive "procedures,
conventions, and past lessons related to the subsystem being
modified." The preceding planning phase produced a milestone
spec about "token refresh handler for the Auth0 integration."
The cheap model generates queries like "authentication token
refresh procedures," "Auth0 integration lessons," "credential
handling conventions."

**Step 2: Per-query hybrid retrieval.** For each query, two
parallel searches run against the index:

- Dense vector search -> top N candidates by embedding similarity
- BM25 keyword search -> top N candidates by lexical matching

N = 20 per retriever per query (tunable; 20 is sufficient for
knowledge bases of hundreds to low thousands of entries).

**Step 3: Per-query fusion and cross-query merge.** For each query,
merge the two result lists using Reciprocal Rank Fusion:
`score = sum(1/(60 + rank))` across retrievers. Combine the
fused lists from all queries, deduplicate entries. Pass the
candidate pool (typically 30-50 unique entries after dedup)
through a cross-encoder reranker, which scores each
(query, entry) pair with full attention over both texts.

**Step 4: Take top 3-5 entries.** The highest-scoring entries
after reranking are injected into the agent's context before
the phase begins, with their metadata (type, created/modified
dates).

Total mechanical context per injection: 3-5 entries (~500-2500
tokens). The 3-5 budget follows SimpleMem's saturation finding:
near-optimal retrieval performance at k=3, diminishing returns
beyond k=5.

Not every phase needs injection. The workflow definition
controls this: a phase either declares a retrieval directive
(and gets injection) or omits it (and relies on inherited
context plus agent-invoked tools). In practice, most phases
that spawn new agents or shift to a different problem domain
should declare a directive.

#### Implementation mapping

The design above maps to the following code locations:

- **Attachment point**: `_step_phase_handshake_core` in
  `koan/tools/koan_tools.py`, executed on the step 0 -> 1 transition of
  every orchestrator phase.
- **Directive location**: `PhaseBinding.retrieval_directive` in
  `koan/lib/workflows.py`. The directive is a static, human-authored
  string set per workflow binding. An empty string disables injection
  for that phase (the curation phase uses an empty string because
  `koan_memory_status` already surfaces the full entry listing).
- **Anchor composition**: `_compose_rag_anchor()` in
  `koan/tools/koan_tools.py`. Order is task description, then all
  `*.md` files in the run directory sorted by mtime ascending.
  `brief.md` (written by intake) is the de facto initiative anchor;
  it appears among the run-dir markdown files sorted by mtime.
- **Rendering**: `render_injection_block()` in
  `koan/memory/retrieval/rag.py` produces a `## Relevant memory`
  markdown block. Phase modules (intake, plan-spec, plan-review,
  execute) prepend this block to their step 1 guidance via
  `ctx.memory_injection`.
- **Failure mode**: Retrieval errors (missing `VOYAGE_API_KEY`, empty
  memory, LanceDB errors) are logged at `warning` and the phase
  proceeds without the injection block.
- **Agent scope**: Orchestrator phases only. Scouts and executors are
  excluded from mechanical injection.

#### Agent-invoked tools

During reasoning, the orchestrator has access to two memory tools.
These complement mechanical injection by handling the agent's
_recognized_ information needs — questions that arise during
reasoning that the agent is aware it cannot answer from its
current context.

**`koan_search(query, filters?)`** is a targeted lookup. The agent
formulates a specific query and gets back raw entries ranked by
relevance. Runs the same hybrid search + reranking pipeline as
mechanical retrieval (steps 3–5 above) but for a single
agent-provided query. Returns the top 3–5 entries as raw markdown
content with metadata. The agent can invoke this as many times as
needed during its reasoning. The optional `filters` parameter
supports metadata filtering, e.g. `type=procedure` to narrow
results to a specific memory type.

Use case: the agent is midway through planning and realizes it
needs to know how the existing secret management works. It calls
`koan_search("secret management pattern .env files")` and gets
the relevant context entry. The mechanical injection surfaced
the lesson about hardcoded credentials (unknown unknown); the
agent tool retrieves the specific implementation pattern it now
knows it needs (known unknown).

**`koan_reflect(question, context?)`** is a synthesized briefing.
The agent poses a broad question and gets back a coherent answer
that draws on multiple entries. Reflect is a single-conversation
LLM tool-calling loop: one strong-tier model conversation plans
query angles, calls a `search` tool as many times as it needs,
reviews accumulated evidence, and calls a `done` tool when it has
enough to synthesize the briefing. The loop is inspired by
Hindsight's CARA reflect architecture and implemented in
`koan/memory/retrieval/reflect.py` (`run_reflect_agent`).

The loop exposes exactly two tools to the model:

- **`search(query, type?, k?)`** — the same hybrid search + reranking
  pipeline used everywhere else (steps 3-5 from mechanical retrieval).
  The optional `type` filter narrows to a specific memory type; `k`
  defaults to 5 and is capped at 20. Every entry returned across the
  loop is tracked in a retrieved-set dict keyed by `entry_id`.
- **`done(answer, memory_ids)`** — terminates the loop. `answer` is
  markdown prose (target 300-500 tokens); `memory_ids` is a list of
  integer entry IDs backing the briefing. The driver validates each
  id against the retrieved set, drops unmatched ids with a log entry,
  and resolves surviving ids to `{id, title}` citation pairs using
  the retrieved-set dict. The calling agent receives
  `{answer, citations, iterations}`.

The model drives the loop itself rather than having the Python caller
orchestrate separate single-turn prompts for planning, sufficiency
judgment, and synthesis. A single conversation lets the model adapt
its next search to what it just found — a capability lost when
control flow lives outside the LLM. The system prompt instructs the
model to decompose the question into 3-5 component searches targeting
different entities and concepts (decomposition examples are included
in the prompt because models default to echoing the user's full
question as a single query otherwise).

The loop is capped at 10 tool calls. Reaching the cap without a
`done` call is a fail-fast: the MCP handler raises
`ToolError("iteration_cap_exceeded")` and no partial briefing is
returned. The iteration cap is a safety rail against runaway loops,
not a soft budget to fill.

No `orient`, `list_entries`, or summary-load step runs at loop start.
The model discovers vocabulary through exploratory searches, the same
way `koan_search` callers do. Pre-loading the summary or listing all
entries moves vocabulary discovery outside the loop and scales badly
as the memory grows.

Citations flow as typed tool arguments, not as text embedded in the
answer prose. The model emits `memory_ids: list[int]`; the driver
resolves titles server-side from the retrieved set. The answer prose
may reference entries by title for readability, but the canonical
citation list is the structured `citations` field in the response.
Parsing citations out of natural-language prose is explicitly out of
scope — structured metadata belongs in tool schemas, not in
free text.

Hallucination validation stays structural. The driver drops any
`memory_id` that was not returned by a `search` call during the loop.
A judge-LLM pass over the answer prose is an evaluation-harness
concern, not a synchronous tooling concern: it lives in `evals/`.

The key differences from Hindsight's reflect that koan does NOT
adopt: no disposition traits (Hindsight uses skepticism,
literalism, and empathy parameters — koan's reflect produces
factual briefings, not opinionated interpretations), and no
opinion formation (Hindsight creates and updates opinions with
confidence scores — koan stores facts and decisions, not
beliefs). Koan also uses one search tool rather than Hindsight's
five-tool surface: there is a single retrieval tier over a flat
entry store, so no distinction between mental-model search,
observation search, recall, and expand is needed.

What koan DOES adopt from Hindsight's reflect: the
single-conversation tool-calling loop (the LLM plans and adapts
its own searches), the evidence-before-synthesis guardrail (the
model must call `search` before claiming something is absent
from memory), the 10-iteration cap, and post-hoc citation
validation against the retrieved set.

#### How the two mechanisms interact

The two mechanisms are complementary, not redundant. Mechanical
injection casts a wider net guided by structural knowledge about
each phase's typical needs. Agent tools make targeted queries
guided by the agent's evolving reasoning.

A concrete example: the execution phase's mechanical injection
surfaces a procedure about "always verify testing policy before
code generation" and a lesson about "executor hardcoded
credentials in docker-compose.yml." The agent reads these,
starts working, and midway through realizes it needs to know
specifically how the existing secret management works — so it
calls `koan_search("secret management pattern .env files")` to
get the relevant context entry. The injection caught the unknown
unknowns (the agent didn't know a testing policy existed); the
agent tool handled the known unknown (the agent recognized it
needed implementation details).

#### Rejected alternative: LLM-generated directives

An alternative design would have the orchestrator generate the
retrieval directive at runtime — asking the LLM "what memory
should I look for before starting this phase?" This was rejected
because it collapses the two retrieval mechanisms into one.

If the orchestrator generates the directive, the queries will
reflect what the orchestrator _thinks_ it needs — which is
exactly what agent-invoked tools already handle. The
orchestrator can already call `koan_search` for anything it
recognizes as a gap. Generating a directive from the
orchestrator's reasoning produces queries biased toward known
unknowns: topics the orchestrator is already aware of and could
query for itself.

The value of mechanical injection comes precisely from the fact
that it does _not_ depend on the agent's assessment of its own
knowledge gaps. The static directive encodes structural knowledge
that the workflow designer has about what each phase type
typically needs — knowledge that is stable across runs and
independent of any particular agent's reasoning state. An
execution phase needs procedures and lessons about the subsystem
being modified, regardless of whether the orchestrator thinks
to ask for them. A verification phase needs testing policies and
known pitfalls, regardless of whether the verifier knows those
exist.

Making the directive dynamic would defeat this purpose. The
unknown unknowns would remain unknown, and the injection would
become a redundant copy of what `koan_search` already does.

### Retrieval backend

The retrieval layer uses an embedded vector database (such as
LanceDB) that provides native hybrid search (dense vectors + BM25)
with metadata filtering. No external server process is required —
the index lives on disk alongside the project.

The index is a derived artifact, not a source of truth. It can be
rebuilt from scratch at any time by re-reading all memory files in
`.koan/memory/`. It should be excluded from version control (e.g.,
added to `.gitignore`).

---

## Scaling path: topic-based clustering

The flat directory structure is the starting point. When the
knowledge base grows to the point where all entries no longer fit
in a cheap model's context window for summary regeneration, that
threshold signals the need for topic-based clustering.

The scaling path introduces topic clusters derived from entry
content similarity, following the approach validated by xMemory
(Hu et al., 2026) and formalized by the (α, C, τ) framework
(Talebirad et al., ICLR 2026). Topic clusters group entries that
are semantically related — a decision about PostgreSQL, the
infrastructure context it relates to, and a lesson about PostgreSQL
migrations would cluster together regardless of their type fields.

At that point, each topic cluster gets its own summary, and the
root `summary.md` is regenerated from the topic summaries rather
than from individual entries. This is the recursive summarization
pattern: summarize the leaves, then summarize the summaries.

The type field remains metadata throughout — it never becomes a
clustering axis. Every hierarchical memory system in the literature
groups by topical similarity, not by cognitive function.

This scaling transition is a future milestone, not a current
concern.

---

## Appendix: project summary example

```markdown
# TrapperKeeper — Project Summary

Last updated: 2026-04-15

TrapperKeeper is a distributed data firewall built by a solo
developer with 20 years of data engineering experience. Runs on a
single Hetzner VM (4 cores, 8GB RAM), deploys via docker-compose.

## Current architecture

- Data storage: PostgreSQL 16.2 (migrated from SQLite, 2026-04-10)
- Session management: Redis 7.x (stateful sessions for compliance)
- Authentication: Auth0 (OAuth2, Management API v2)
- Background jobs: Bull on Redis
- Deployment: docker-compose, manual SSH, secrets via .env files

## Key policies

- No unit tests. Integration tests only.
- No comments except for non-obvious business logic.
- Python: ruff, default config.
- Secrets must never appear in docker-compose.yml; use .env.

## Key procedures

- Always verify testing policy before code generation tasks.
- Decompose database migrations into schema + application milestones.
- Check variables.css before adding new CSS styles.

## Recent work

- #48 (2026-04-15): Background job processor via Bull/Redis
- #42 (2026-04-10): User authentication via Auth0

## Known pitfalls

- Executor tends to generate unit tests; always verify testing policy.
- Executor tends to hardcode credentials; always check existing secret
  management patterns before modifying infrastructure.
```

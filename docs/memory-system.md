# Koan Memory System — Specification v3

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

---

## Entry format

Each memory entry is a standalone markdown file consisting of three
parts: YAML frontmatter, a contextual introduction, and a prose body.

### YAML frontmatter

Structured metadata that enables programmatic operations — staleness
detection, status filtering, cross-referencing, and retrieval
filtering.

```yaml
---
title: PostgreSQL for Auth Service
type: decision
date: 2026-04-10
source: user-stated
status: active
tags: [auth, postgresql, data-storage]
supersedes: null
related: [context/0002-infrastructure.md]
---
```

Required fields:

- **title**: Short descriptive name, used in listings and summaries
- **type**: One of `decision`, `context`, `lesson`, `procedure`,
  `milestone`
- **date**: The date the fact became true or was observed (ISO 8601)
- **source**: How the memory was captured — `user-stated`,
  `llm-inferred`, or `post-mortem`
- **status**: `active`, `review-needed`, `deprecated`, or `archived`

Optional fields:

- **tags**: Free-form labels for retrieval filtering
- **supersedes**: Path to the entry this one replaces (if any)
- **related**: Paths to related entries

### Contextual introduction

A 1–3 sentence paragraph immediately following the frontmatter that
situates the entry within the project. This introduction is written
at capture time and becomes a permanent part of the file. It is not
generated at retrieval or embedding time.

This follows Anthropic's contextual retrieval technique, which
demonstrated a 35% reduction in retrieval failures when contextual
information is prepended to chunks before embedding. The critical
design choice: the contextual introduction is written once and stored
in the file, rather than generated dynamically at embedding time.

Rationale for baking it into the file:

1. **Consistency.** The embedding and the file content are always in
   sync. There is no discrepancy between what the retrieval layer
   indexed and what the file contains.

2. **Determinism.** It is possible to check whether an embedding has
   already been computed for a file by comparing content hashes.
   Dynamic contextual generation would produce slightly different
   wordings each time, making hash-based change detection unreliable.

3. **Transparency.** A human reading the file sees exactly what the
   retrieval system sees. Nothing is hidden in an intermediate layer.

The tradeoff is denormalization. If the project is renamed or a
major structural fact changes, all contextual introductions that
reference it become stale and must be updated. This is acceptable —
such changes are rare, and the memory review workflow can surface
and batch-update affected entries.

### Prose body

The main content, written in event-style following the writing
discipline described below.

### Complete example

```markdown
---
title: PostgreSQL for Auth Service
type: decision
date: 2026-04-10
source: user-stated
status: active
tags: [auth, postgresql, data-storage]
supersedes: null
related: [context/0002-infrastructure.md]
---

This entry is a decision record from the TrapperKeeper project,
a distributed data firewall. It documents the choice of primary
data store for the authentication service.

On 2026-04-10, user decided to migrate the auth service from SQLite
to PostgreSQL 16.2. Rationale: SQLite could not handle concurrent
write loads from the new worker pool (>50 connections). Alternatives
rejected: SQLite WAL mode (single-writer limitation), CockroachDB
(operational complexity too high for a two-person team). Decision
surfaced during intake when user described timeout errors under load.
```

---

## Writing discipline

All memories are written as **temporally grounded, absolute facts**.
This quality discipline is validated by SimpleMem (Liu et al., 2026),
whose ablation showed that removing temporal normalization and
coreference resolution reduced Temporal F1 by 56.7%. The EMem paper
(Zhou et al., 2025, "A Simple Yet Strong Baseline for Long-Term
Conversational Memory of LLM Agents") grounds this in neo-Davidsonian
event semantics: treating events as single units with multiple
arguments outperforms decomposing them into relation triples.

### Rules

1. **Every statement includes a date.** The date the fact became true
   or was observed. If unknown, use the recording date.

2. **Attribute claims to their source.** "User stated...", "LLM
   inferred...", "Post-mortem identified...".

3. **No forward-looking language.** Not "we will" but "On [date], user
   stated the plan was to...".

4. **Name things concretely.** Not "the database" but "PostgreSQL 16.2"
   or "the auth service's primary data store."

5. **Each entry must stand alone.** Interpretable without any other
   file, true regardless of when it is read.

Source attribution embedded in the prose serves as the primary trust
signal. User-stated facts carry higher trust than LLM-inferred facts.
No external metadata database is needed for trust assessment.

### Examples

Bad — relative, will become stale:

> We use PostgreSQL for the auth service.

Good — temporally grounded, always true as a historical fact:

> On 2026-04-10, user decided to use PostgreSQL 16.2 for the auth
> service's data storage, replacing SQLite.

---

## Memory types

Koan organizes memories into five document types, each corresponding
to a distinct retrieval intent — a kind of question an agent needs
answered.

### Decisions — *Why is the project the way it is?*

The most critical memory type. Decisions capture **why** the project
is the way it is — not just what was chosen, but what was rejected
and why.

Each decision entry should capture, where known: what was decided,
the rationale (constraints that drove the choice), alternatives
considered and rejected, and how the decision surfaced (intake,
mid-workflow correction, post-mortem).

Decisions include both explicit choices (user-stated) and implicit
choices (LLM-inferred from user behavior). Implicit decisions are
marked as such via the `source` field.

### Context — *What do I need to know that isn't in the code?*

Objective facts about the project, team, domain, and infrastructure
that are not derivable from the codebase and are expected to remain
stable across sessions. Team size, deployment setup, external
dependencies, business constraints.

Context entries are split into project-scoped (in `.koan/memory/
context/`) and user-scoped (in `.koan/user/context/`). User context
includes background, experience level, coding preferences, and style.
It applies across all projects.

### Lessons — *What went wrong before?*

Mistakes made during workflows and the corrections applied. Each
entry captures: what happened, what the user did to correct it,
root cause, and what should change to prevent recurrence.

A lesson often produces a new decision or procedure, but the lesson
itself is the error record — the ground truth about what went wrong.

### Procedures — *How should I approach things in this project?*

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

### Milestones — *What work has been done?*

A running record of completed workflows. Milestones capture *that*
something was done, not the full detail of how. Their primary purpose
is enabling project summary generation and providing future intake
phases a quick history.

### Project summary (derived)

A synthesized overview regenerated after each workflow completes.
Unlike memory entries, the summary is produced by reading the other
memory files and synthesizing them into a concise briefing. It lives
at `.koan/memory/summary.md` and does not have the standard entry
format (no sequential number, no contextual introduction).

The summary is the first thing an LLM reads when starting any
workflow. It is loaded in full at intake (not retrieved via search)
as long as it fits within a budget of ~2000 tokens. This follows the
coarsening–traversal (C–T) coupling principle from "Toward a Theory
of Hierarchical Memory for Language Agents" (ICLR 2026):
self-sufficient representatives can be loaded in full (collapsed
search), but only while they fit the token budget.

---

## File organization

```
.koan/
  memory/
    summary.md                          # tier 1: root summary (whole project)
    decisions/
      _index.md                         # tier 2: condensed summary of all decisions
      0001-postgresql-for-auth.md       # tier 3: individual entries
      0002-no-unit-tests.md
      0003-redis-session-management.md
    context/
      _index.md
      0001-team-structure.md
      0002-infrastructure.md
      0003-auth0-integration.md
    lessons/
      _index.md
      0001-unit-test-generation.md
    procedures/
      _index.md
      0001-testing-policy-check.md
      0002-database-migration-steps.md
    milestones/
      _index.md
      0042-user-authentication.md
      0048-background-jobs.md

  user/                                 # user-global (shared across projects)
    context/
      _index.md
      0001-background.md
      0002-coding-preferences.md
    lessons/
      _index.md
      0001-credential-hardcoding.md
    procedures/
      _index.md
      0001-migration-decomposition.md
```

### Three-tier summary hierarchy

The memory system maintains summaries at three levels, following the
RAPTOR recursive abstractive retrieval pattern (Sarthi et al., ICLR
2024). Each level provides a self-sufficient representation that can
answer queries at its resolution without drilling deeper.

**Tier 1: Root summary** (`summary.md`). A project-wide overview
covering architecture, policies, recent work, and known pitfalls.
Always loaded in full at intake. Budget: ~2000 tokens.

**Tier 2: Type-level indexes** (`decisions/_index.md`, etc.). Each
type folder contains an `_index.md` that condenses all active entries
in that folder into a single prose summary. An agent needing a broad
view of "all decisions" or "all procedures" can load the relevant
`_index.md` without retrieving individual entries. Budget: ~500
tokens each.

**Tier 3: Individual entries** (`0001-postgresql-for-auth.md`). The
full knowledge entries, retrieved via hybrid search when the agent
needs specific detail that the summaries don't provide.

The root `summary.md` is regenerated from the type-level `_index.md`
files rather than reading every individual entry directly. This is
RAPTOR's recursive summarization: summarize the leaves, then
summarize the summaries.

Type-level `_index.md` files are generated artifacts, like
`summary.md`. They carry a simple frontmatter block:

```yaml
---
type: index
covers: [0001, 0002, 0003]
token_count: 420
last_generated: 2026-04-15
---
```

Example `decisions/_index.md`:

```markdown
---
type: index
covers: [0001, 0002, 0003]
token_count: 380
last_generated: 2026-04-15
---

TrapperKeeper's active architectural decisions cover three areas.
Data storage uses PostgreSQL 16.2 for the auth service, chosen over
SQLite (concurrency limits) and CockroachDB (operational complexity)
as of 2026-04-10. Testing policy prohibits unit tests in favor of
integration tests only, established 2026-04-08. Session management
uses Redis 7.x with stateful sessions for compliance requirements,
decided 2026-04-12.
```

### Naming convention

Files are named `NNNN-short-description.md` where `NNNN` is a
zero-padded sequential number within the type folder. The number
provides stable ordering and prevents filename collisions. The
description is a human-readable slug derived from the title.

New entries are assigned the next available number in their type
folder. Numbers are never reused — if entry `0005` is deleted, the
next entry is still `0006`.

### Version control

The `.koan/memory/` directory is checked into version control
alongside the project's source code. This means memory changes
appear in diffs, can be reviewed in pull requests, and have full
git history. The `.koan/user/` directory is stored outside the
project repository (e.g., in `~/.koan/user/`) since it applies
across all projects.

---

## Memory lifecycle

Memory is created and maintained through a single mechanism —
**curation** — invoked with different sources and directives
depending on the context. All memory modifications require explicit
user review.

### The curation workflow

Curation is a unified workflow that reads source material, reflects
on it in the context of existing memory, proposes changes, and
presents them to the user for review. It follows the same pattern
regardless of what triggered it:

1. **Read source material.** The source varies by invocation: a
   workflow transcript, the existing memory corpus, codebase files,
   user-provided documents, or a combination.

2. **Read existing memory.** Load all `_index.md` files for
   orientation, plus individual entries relevant to the source
   material (via retrieval or full scan).

3. **Reflect.** The curation agent evaluates the source against
   existing memory. Depending on the directive, it may:
   - Identify new knowledge to capture
   - Find existing entries that need updating
   - Detect stale, contradictory, or duplicate entries
   - Surface gaps in coverage
   - Evaluate lessons for procedure generation
   - Assess whether the type-level organization still fits

4. **Conduct Q&A with the user** (when the directive calls for it).
   Ask clarifying questions to fill gaps, verify assumptions, or
   resolve ambiguities.

5. **Propose changes.** Each proposed change is a complete entry
   (for creates) or a diff (for updates), organized by operation:
   - **Create**: New entry with full frontmatter, contextual
     introduction, and prose body
   - **Update**: Modified content for an existing entry
   - **Merge**: Two or more entries combined into one
   - **Deprecate**: Status change to `deprecated`
   - **Promote / demote**: Move between project-local and user-global
   - **Archive**: Remove from active retrieval

6. **User reviews each proposed change.** The user approves, edits,
   or rejects each change individually. The agent does not modify
   memory without explicit user approval.

7. **Write approved changes to disk.** New entries get the next
   available sequence number in their type folder.

8. **Regenerate summaries.** Type-level `_index.md` files are
   regenerated for each type folder that had changes. The root
   `summary.md` is regenerated from the updated `_index.md` files.

9. **Re-index.** The sync layer detects changed files and updates
   the retrieval index.

### Curation directives

The same workflow serves all memory operations through different
directives:

**Post-mortem curation** runs at the end of every koan workflow.
Source: the workflow transcript (user messages, agent outputs,
interventions, escalations). Directive: reflect on what went well,
what went wrong, what decisions were made (explicitly or implicitly),
what patterns emerged. Capture decisions, lessons, procedures,
context facts, and a milestone record.

**Review curation** is triggered on-demand, on a schedule, or at
project initialization. Source: the existing memory corpus (and
optionally the codebase). Directive: assess memory health — identify
stale entries, contradictions, gaps, entries that should be merged,
lessons lacking procedures, deprecated entries to archive. Conduct
Q&A with the user to fill gaps and verify facts.

**Bootstrap curation** runs when koan is first set up for a project.
Source: the codebase, any existing documentation, and user interview.
Directive: capture baseline project context, team structure,
conventions, constraints, and architectural decisions already in
effect.

**Document curation** ingests specific source material the user
provides. Source: architecture docs, specs, design documents, or
any other material. Directive: extract relevant knowledge and
organize it into memory entries.

### Triggering curation

Curation is triggered:

- **Automatically** at the end of every koan workflow (post-mortem
  directive).
- **On explicit user request** (review, bootstrap, or document
  directive).
- **On suggestion** after N completed workflows, koan suggests a
  review curation. Configurable, e.g. every 5 workflows.
- **At project initialization** (bootstrap directive).

### Model tier assignments

Curation uses **strong-tier models** for reflection and proposal
generation. This is where judgment matters — what to capture, how
to phrase it, whether existing entries need updating.

Mechanical retrieval at intake uses **no LLM** for the search
itself. Hybrid vector + BM25 search, cross-encoder reranking, and
metadata filtering are all mechanical operations.

The `koan_reflect` tool uses a **cheap-tier model** for query
generation (decomposing a broad question into multiple search
angles) and synthesis (combining retrieved entries into a coherent
briefing). This does not require the strong model — it is
summarizing existing knowledge, not making new decisions.

Query rewriting for low-confidence retrievals can also use a
**cheap-tier model** to reformulate queries before retrying.

### Direct human editing

Because memory files are plain markdown in version control, humans
can edit them directly at any time — in their editor, via a pull
request, or through any other workflow. The sync layer detects
changes and re-indexes modified files.

When humans edit files directly, they should maintain the entry
format (frontmatter + contextual introduction + prose body) and
update the `date` field if the content changes substantively.

---

## Retrieval

Koan builds its own retrieval layer over the memory files rather
than delegating to a conversational memory system. This is because
koan's memory entries are already well-structured, self-contained
documents — running them through a fact extraction pipeline (as
systems like Hindsight do) would be destructive, stripping the
framing and rationale that make entries valuable.

### Entry grain size

Each memory entry is 100–500 tokens: large enough to be
self-contained, small enough that retrieving 3–5 entries fits within
a reasonable token budget. This grain size is a deliberate design
choice supported by three converging arguments.

**Empirical evidence on chunk size.** Mem0's benchmark (Table 2)
shows that for atomic factual queries, small chunks (128–256 tokens)
outperform large chunks (1024–2048 tokens) by ~32% when retrieving
a single result. However, this data comes from conversational memory
where answers are individual facts ("Alice's job is X"). Koan's
knowledge is structurally different — a decision entry bundles a
choice with its rationale, rejected alternatives, and surfacing
context. These elements are not independent facts; they are one
coherent unit of knowledge.

**The neo-Davidsonian argument (Zhou et al., EMem 2025).** When
knowledge is relational — when the value lies in connections between
elements — atomizing it into independent facts destroys the
structure that makes it useful. If a decision ("chose PostgreSQL
over SQLite due to concurrency, rejecting CockroachDB for
operational complexity") is split into three separate atomic facts,
a query about CockroachDB retrieves the CockroachDB fact but loses
the decision context. The retriever would need to find all three
facts and the LLM would need to reassemble them, requiring
multi-hop reasoning at query time — the operation that degrades
performance most across all benchmarks.

**Koan's knowledge is inherently relational.** Koan stores
architectural decisions with rationale and alternatives, lessons
with root causes and prevention strategies, procedures with
conditionals and scope boundaries. These are not atomic preferences
("user prefers tabs over spaces") — they are structured arguments
where the rationale, the alternatives, and the context are all
essential to the entry's value. The grain must be large enough to
keep the relations intact within each entry, while small enough
that a few retrieved entries fit the token budget.

The grain size is therefore not "as small as possible" but "as
small as possible while preserving the coherence of each knowledge
unit." For koan's content type, that is 100–500 tokens per entry.

### Indexing

The sync layer watches `.koan/memory/` and indexes each file as a
single chunk. Because entries are written to be self-contained and
are typically 100–500 tokens, most entries can be embedded whole
without further chunking.

For each entry, the sync layer:

1. Reads the file content (frontmatter + contextual introduction +
   prose body)
2. Parses the YAML frontmatter into structured metadata
3. Computes a content hash for change detection
4. Generates a dense embedding of the full text (including the
   contextual introduction)
5. Indexes the text for BM25 keyword search
6. Stores the embedding, BM25 index entry, and metadata

The `_index.md` summary files and `summary.md` are also indexed
alongside individual entries. Because these summaries are
self-sufficient (following the RAPTOR/C–T coupling principle), they
participate in collapsed search — a broad query may match a
type-level summary directly, while a specific query matches an
individual entry.

Re-indexing is triggered when a file's content hash changes. Because
the contextual introduction is baked into the file, the hash
reliably indicates whether re-embedding is needed.

### Two retrieval paths

Koan provides two distinct retrieval mechanisms: **mechanical context
injection** (automatic, at the start of every intake) and
**agent-invoked tools** (on-demand, during reasoning).

#### Mechanical context injection

At the start of every intake phase, before the agent begins
reasoning, koan automatically loads baseline context. The pipeline
has six steps:

**Step 1: Load project summary.** `summary.md` is loaded in full.
Always present, not retrieved via search. Budget: ~2000 tokens.

**Step 2: Generate search queries.** From the current task
description, generate 1–3 search queries that cover different
angles of the task. Example: task "implement OAuth2 authentication
via Auth0" produces queries like "authentication architecture
decisions," "Auth0 integration context," "auth service procedures."
These can be generated mechanically (extract key entities, expand
with type-relevant terms) or by a cheap-tier model.

**Step 3: Per-query hybrid retrieval.** For each query, two
parallel searches run against the index:
- Dense vector search → top N candidates by embedding similarity
- BM25 keyword search → top N candidates by lexical matching
N = 20 per retriever per query (tunable; 20 is sufficient for
knowledge bases of hundreds to low thousands of entries).

**Step 4: Per-query fusion.** For each query, merge the two result
lists using Reciprocal Rank Fusion: `score = Σ 1/(60 + rank)`
across retrievers. Output: one ranked list per query.

**Step 5: Cross-query merge and reranking.** Combine the fused
lists from all queries, deduplicate entries. Pass the candidate
pool (typically 30–50 unique entries after dedup) through a
cross-encoder reranker, which scores each (query, entry) pair
with full attention over both texts.

**Step 6: Take top 3–5 entries.** The highest-scoring entries
after reranking are injected into the agent's context alongside
the summary, with their metadata (type, date, source, status).

Total mechanical context: summary (~2000 tokens) + 3–5 entries
(~500–2500 tokens) = ~2500–4500 tokens of memory context. The
3–5 budget follows SimpleMem's saturation finding: near-optimal
retrieval performance at k=3, diminishing returns beyond k=5.

Note: the `_index.md` summary files participate in retrieval
alongside individual entries (collapsed search). A broad query
may match a type-level summary directly; a specific query matches
an individual entry. The reranker decides which level is most
relevant for each query.

#### Agent-invoked tools

During reasoning, the intake agent has access to two memory tools.

**`koan_search(query, filters?)`** is a targeted lookup. The agent
formulates a specific query and gets back raw entries ranked by
relevance. Runs the same hybrid search + reranking pipeline as
mechanical retrieval (steps 3–6 above) but for a single
agent-provided query. Returns the top 3–5 entries as raw markdown
content with metadata. The agent can invoke this as many times as
needed during its reasoning.

Use case: "what is the testing policy?" → returns the relevant
procedure entry directly. No LLM involved in the retrieval
pipeline.

**`koan_reflect(question, context?)`** is a synthesized briefing.
The agent poses a broad question and gets back a coherent answer
that draws on multiple entries. This is modeled as a mini-agent
(cheap-tier model) running an evidence-gathering loop, inspired
by Hindsight's CARA reflect architecture.

The reflect tool runs the following agentic loop:

**Step 1: Orient.** The reflect agent loads the project summary
and relevant `_index.md` files to understand what knowledge areas
exist. This is a direct file read, not a search.

**Step 2: Plan queries.** Based on the question and the
orientation context, the agent generates 3–5 search queries from
different angles. Example: question "what constraints and patterns
should guide SDK design?" produces queries like "SDK architecture
decisions," "sensor lifecycle procedures," "testing philosophy
conventions," "fail-safe default requirements," "past SDK-related
lessons."

**Step 3: Gather evidence.** For each query, run the standard
retrieval pipeline (hybrid search + reranking, steps 3–6 from
mechanical retrieval). Collect the top results across all queries.

**Step 4: Evaluate sufficiency.** The agent reviews the gathered
entries and assesses whether they adequately answer the question.
If critical gaps remain (the question asks about SDK testing but
no testing-related entries were retrieved), generate 1–2
additional targeted queries and retrieve more. This loop runs
up to 3 iterations to prevent runaway searches.

**Step 5: Synthesize.** The agent reads all gathered entries
(typically 8–15 after deduplication) and produces a coherent
300–500 token briefing that answers the original question. The
synthesis connects knowledge across different entry types —
linking a decision about fail-safe defaults to a procedure about
testing to a lesson about SDK initialization failures. Each claim
in the briefing cites the specific entry it draws from (by file
path).

**Step 6: Return.** The briefing is returned to the calling agent
as the tool's output.

The key differences from Hindsight's reflect that koan does NOT
adopt:
- **No disposition traits.** Hindsight uses skepticism, literalism,
  and empathy parameters to shape how the agent interprets facts.
  Koan's reflect produces factual briefings, not opinionated
  interpretations. The project's knowledge speaks for itself.
- **No opinion formation.** Hindsight's reflect creates and updates
  opinions with confidence scores. Koan's memory system stores
  facts, decisions, and procedures — not beliefs. The reflect tool
  synthesizes existing knowledge; it does not form new conclusions.
- **No mental models.** Hindsight's reflect checks pre-computed
  summary responses first. Koan's `_index.md` files serve a similar
  function (compressed type-level overviews) but are loaded during
  orientation rather than as a separate retrieval tier.

What koan DOES adopt from Hindsight's reflect:
- **The agentic loop.** The reflect tool is not a single LLM call
  but an iterative evidence-gathering process that can make
  multiple searches and evaluate sufficiency.
- **Hierarchical retrieval.** Check summaries for orientation first,
  then search individual entries for detail.
- **Evidence-before-synthesis guardrail.** The agent must gather
  entries before producing a briefing — it cannot answer from its
  parametric knowledge alone.
- **Citation validation.** The briefing can only cite entries that
  were actually retrieved during the evidence-gathering loop.

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

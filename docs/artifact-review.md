# Artifact Review

Protocol for presenting a written artifact to the user and collecting feedback.
Used by the brief-writer phase; reusable for any future markdown artifact that
requires a review-revise loop before pipeline advancement.

> Parent doc: [architecture.md](./architecture.md)
>
> IPC model: [ipc.md](./ipc.md)

---

## Overview

The artifact review protocol pauses subagent execution while the user reads a
rendered markdown artifact and either accepts it or provides revision feedback.
The review loop is LLM-driven: the subagent writes the artifact, calls
`koan_review_artifact`, revises on feedback, and calls the tool again. The
protocol is stateless -- each invocation is a fresh request.

---

## Interaction Model

When `koan_review_artifact` is called via MCP, the tool handler:

1. Reads the file at `path` to obtain raw markdown content
2. Creates a `PendingInteraction` with type `"artifact-review"` and an `asyncio.Future`
3. Stores it in `AgentState.pending_tool`
4. Pushes SSE `"artifact-review"` event to connected browsers
5. Awaits the Future -- the MCP HTTP connection stays open
6. When the user responds (Accept or feedback), the web endpoint resolves the Future
7. Returns feedback string to the LLM as the MCP tool result

There is no file-based IPC. The entire interaction is in-process via
`asyncio.Future`.

---

## Tool Interface

**Name:** `koan_review_artifact`

**Parameters:**

- `path` (string) -- file path of the artifact to review
- `description` (string, optional) -- context for the reviewer

**Return values:**

```
User feedback:
Accept

--- or ---

User feedback:
The goals section needs a latency metric. Constraint #3 is too broad.
```

**LLM behavior on response:**

- `"Accept"` -> call `koan_complete_step`
- Any other text -> revise the artifact, call `koan_review_artifact` again

---

## "Accept" Is Verbatim Text

When the user clicks "Accept" in the web UI, the feedback string sent to the
subagent is literally `"Accept"`. When the user provides feedback, it is their
typed text. Both cases travel the same code path.

**Why:** A dedicated `accepted: boolean` field would create two response shapes
and require branching. Uniform text keeps the tool stateless and lets the LLM
decide how to proceed.

---

## Web UI Component

The artifact review is rendered as a server-side HTML fragment via
`koan/web/templates/fragments/interaction_artifact_review.html`. The template
receives the raw markdown content and renders it server-side.

**Layout:**

```
+------------------------------------------+
|  Review: <artifact_path>                 |
|  ---------------------                   |
|  +----------------------------------+    |
|  |  [rendered markdown content]     |    |
|  +----------------------------------+    |
|  +----------------------------------+    |
|  | Feedback (optional)              |    |
|  +----------------------------------+    |
|  [Send Feedback]          [Accept]       |
+------------------------------------------+
```

**Behavior:**

- Server renders markdown content in the HTML fragment
- "Accept" -> `POST /api/artifact-review` with `{ feedback: "Accept" }`
- "Send Feedback" -> `POST /api/artifact-review` with `{ feedback: text }`
- HTMX swaps the fragment on SSE events (new review, review cleared)

---

## HTTP Endpoint

**`POST /api/artifact-review`** in `koan/web/interactions.py`

Validates request parameters and resolves the pending `asyncio.Future` in the
agent's `PendingInteraction`. Returns `{ ok: true }` on success, error on
validation failure or missing pending interaction.

---

## SSE Events

| Event                       | Direction         | Payload                                               |
| --------------------------- | ----------------- | ----------------------------------------------------- |
| `artifact-review`           | server -> browser | `{ request_id, artifact_path, content, description }` |
| `artifact-review-cancelled` | server -> browser | `{ request_id }`                                      |

SSE events are pushed directly from the tool handler. On browser reconnect,
pending reviews are replayed so the user does not lose the review form.

---

## Review Loop

```
subagent calls koan_review_artifact({ path: ".../brief.md" }) via MCP
  -> MCP endpoint reads brief.md content
  -> creates PendingInteraction { type: "artifact-review", future: Future() }
  -> pushes SSE "artifact-review" event to browsers
  -> awaits Future

user sees rendered markdown in web UI
  -> clicks "Accept" or types feedback
  -> POST /api/artifact-review -> resolves Future

MCP handler returns feedback as tool result
  -> subagent receives "User feedback:\n{feedback}"

if feedback == "Accept":
  LLM calls koan_complete_step -> phase advances
else:
  LLM revises artifact, calls koan_review_artifact again
  (loop repeats with fresh PendingInteraction)
```

---

## Reusability

The artifact review mechanism is not epic-brief-specific. Any planning phase
that produces a markdown artifact can use the same pattern:

1. Write the artifact to the epic directory
2. Call `koan_review_artifact` with the path
3. Process the feedback string: revise and re-invoke, or accept and advance

Future phases that could use this pattern: core flows document, technical plan,
architecture decision record. Adding a new phase requires only: assigning the
`koan_review_artifact` permission to the new role (in `koan/lib/permissions.py`)
and implementing the review loop in the phase's step guidance.

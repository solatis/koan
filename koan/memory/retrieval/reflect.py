# LLM-driven reflection loop over project memory.
#
# run_reflect_agent runs a single-conversation Gemini tool-calling loop that
# searches memory as many times as needed, then returns a cited briefing.
# Intended for broad synthesis questions that cannot be answered by a single
# koan_search call.
#
# The Gemini client is constructed directly inside run_reflect_agent (no
# injectable parameter). Evaluation is handled through evals/, not unit mocks.

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from google import genai
from google.genai import types

from ..types import MemoryEntry
from ...logger import get_logger
from .backend import search as retrieval_search
from .index import RetrievalIndex
from .types import SearchResult

log = get_logger("memory.retrieval.reflect")

DEFAULT_MODEL = "gemini-flash-latest"
MAX_ITERATIONS = 10

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a research analyst producing a cited briefing from a software
project's memory store. Your reader is a downstream agent making a
decision; they need traceable claims, not opinions. Every claim in
your briefing must come from an entry returned by a `search` call in
THIS conversation. No general knowledge, no inference beyond what
entries state, no speculation. If the memory does not cover
something, name the gap and move on -- "known unknowns" is data, not
failure.

The store holds markdown entries written in dated event-style. Each
entry has one of four types -- use the `type` filter when the question
is clearly scoped to one:

  decision   Choices made, alternatives rejected, rationale. Filter
             when the question asks WHY the project is the way it is
             or WHAT was chosen over what.
  context    Stable project, team, or infra facts not derivable from
             code. Filter when the question asks about the stack, the
             team, external deps, or the deployment setup.
  lesson     Past mistakes and their corrections. Filter when the
             question asks about incidents, regressions, or what went
             wrong before.
  procedure  Actionable rules and conventions. Filter when the
             question asks HOW something is done or what the
             conventions are.

A question often spans types -- run one search per type when it does.
Leave `type` unset to scan everything.

## Workflow (one pass)

1. Decompose. Pull the entities and concepts out of the question.
   Issue one `search` per entity or concept -- 3 to 5 calls. NEVER
   paste the user's question verbatim as a single query.

2. Fill gaps. If the first pass left a named concept unexplored, run
   ONE more targeted search with different vocabulary. Stop there;
   the 10-call loop cap is a hard failure, not a budget to spend.

3. Draft the briefing in your head. 300-500 tokens of markdown prose.
   Open with the most load-bearing finding. Use concrete names and
   dates from the entries (e.g., "PostgreSQL 16.2, chosen on
   2026-04-10"), not vague paraphrases. Close by naming what the
   memory does NOT cover about the question -- omissions are data.

4. Select citations, then call `done`. For EACH claim in your draft,
   name which retrieved entry backs it. An entry backs a claim only
   if removing that entry would force you to drop the claim. Entries
   you saw in search results but did not rely on are NOT citations --
   exclude them from `memory_ids`. Citing seen-but-unused entries is
   the most common failure mode of this agent; actively filter.

## Worked example

Question: "How do we handle session tokens?"

Entities/concepts: "session tokens", "authentication", "storage",
"rotation/refresh". Decomposed searches:
  search("session token storage",     type=decision)
  search("authentication middleware", type=context)
  search("token refresh or rotation", type=procedure)

Suppose the pool across these calls is:
  [#12] "Session tokens stored in Redis 7.x (2026-03-01)"        context
  [#18] "Decided against JWT in cookies (2026-02-10)"             decision
  [#21] "Migrated auth service SQLite -> Postgres (2026-04-10)"   decision
  [#24] "Executor hardcoded tokens in docker-compose (2026-03-22)" lesson
  [#31] "Python style: ruff default config (2026-01-15)"          context

Draft claims mapped to backing entries:
  "Session tokens live in Redis 7.x."           -> backed by #12
  "JWT-in-cookies was rejected on 2026-02-10."  -> backed by #18
  "A prior incident hardcoded tokens in the
   compose file; watch for this in IaC diffs."  -> backed by #24

Memory entries #21 (auth DB migration) and #31 (ruff config) were
retrieved but do not back any claim in this briefing. Correct
citation list is [12, 18, 24]. A drifted list would be
[12, 18, 21, 24, 31] -- do not do this.

## Sparse results

If your searches return little that is on-topic, do not pad the
briefing with speculation to hit the token target. Write a shorter
briefing that names the gap. "Memory does not cover X" is a valid
finding; inventing X is not.

## Termination

Single-turn, non-conversational. Do not ask follow-up questions; no
one will answer. Do not offer alternatives or next steps. Call `done`
as soon as you have enough to write the briefing. The loop is capped
at 10 tool calls total -- exceeding the cap returns no answer at
all, so spend calls on evidence, not deliberation.
"""

# ---------------------------------------------------------------------------
# Tool declarations
# ---------------------------------------------------------------------------

_SEARCH_DECL = types.FunctionDeclaration(
    name="search",
    description=(
        "Hybrid semantic + BM25 search over the project memory store. "
        "Returns an array of entries; each entry has fields: entry_id "
        "(int, use this in memory_ids), title, type, score, body (full "
        "markdown content), created, modified. Rank is by score. Call "
        "this multiple times with decomposed queries to cover different "
        "facets of the question."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description=(
                    "A single entity or concept -- NOT the user's full "
                    "question. Good: 'session token storage', 'Auth0 "
                    "integration', 'PostgreSQL migration'. Bad: 'how "
                    "does auth work', 'tell me about the database'. "
                    "Prefer concrete named things ('PostgreSQL 16.2') "
                    "over abstractions ('the database'). Run 3-5 such "
                    "queries per question to cover its entities and "
                    "concepts."
                ),
            ),
            "type": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Optional filter. decision = choices made and "
                    "alternatives rejected; context = stable project/"
                    "team/infra facts; lesson = past mistakes and "
                    "their corrections; procedure = actionable rules "
                    "or conventions. Set it when the question is "
                    "clearly scoped to one type; leave unset to scan "
                    "all types."
                ),
                enum=["decision", "context", "lesson", "procedure"],
            ),
            "k": types.Schema(
                type=types.Type.INTEGER,
                description=(
                    "Number of entries to return. Default 5 is almost "
                    "always right. Raise to 10-20 only when you "
                    "suspect a topic is well covered and you want "
                    "recall over precision. Hard cap: 20."
                ),
            ),
        },
        required=["query"],
    ),
)

_DONE_DECL = types.FunctionDeclaration(
    name="done",
    description=(
        "Emit the final cited briefing and terminate the loop. Call "
        "this only when every claim in your drafted answer is backed "
        "by a specific entry returned by a prior `search` call in "
        "this conversation."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "answer": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Markdown briefing, 300-500 tokens. Open with the "
                    "most load-bearing finding. Use concrete entity "
                    "names and dates from the entries, not vague "
                    "paraphrases. Close by naming what the memory "
                    "does NOT cover about the question. Do NOT "
                    "include entry IDs, filenames, or UUIDs in this "
                    "text -- citations go in memory_ids, not in the "
                    "prose."
                ),
            ),
            "memory_ids": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.INTEGER),
                description=(
                    "Entry IDs that back specific claims in `answer`. "
                    "Include an id iff removing that entry from your "
                    "evidence would force you to drop some claim in "
                    "the answer. Do NOT include entries that appeared "
                    "in search results but were not relied on -- that "
                    "mistake (citing seen entries rather than used "
                    "entries) is the primary failure mode of this "
                    "tool. Dedupe; order does not matter."
                ),
            ),
        },
        required=["answer", "memory_ids"],
    ),
)

# Single Tool object wrapping both declarations so they appear in one tool_use block.
_TOOLS = [types.Tool(function_declarations=[_SEARCH_DECL, _DONE_DECL])]

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class ReflectTraceEvent:
    iteration: int
    tool: str           # "search" or "done"
    args: dict          # tool args as emitted by the LLM
    result_count: int | None = None   # populated for search only, after dispatch


@dataclass
class Citation:
    id: int
    title: str


@dataclass
class ReflectResult:
    answer: str
    citations: list[Citation]
    iterations: int


class IterationCapExceeded(Exception):
    def __init__(self, iterations: int) -> None:
        super().__init__(
            f"reflect loop exceeded {iterations} iterations without calling done"
        )
        self.iterations = iterations


# ---------------------------------------------------------------------------
# API-key helpers (module-local, mirroring llm.py pattern)
# ---------------------------------------------------------------------------

# Kept module-local so reflect's mid-tier client (gemini-flash-latest)
# stays isolated from llm.py's cheap-tier client (gemini-flash-lite-latest).
def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is required"
        )
    return key


def _model() -> str:
    return os.environ.get("KOAN_REFLECT_MODEL") or DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable: take plain data, no LLM involvement)
# ---------------------------------------------------------------------------

def _resolve_citations(
    memory_ids: list[int],
    retrieved: dict[int, MemoryEntry],
) -> list[Citation]:
    """Filter memory_ids by membership in retrieved set, preserve order, dedupe.

    Drops any id not present in the retrieved set (hallucination guard) and
    logs each dropped id at INFO level. Returns Citation(id, title) pairs.
    """
    seen: set[int] = set()
    out: list[Citation] = []
    for eid in sorted(memory_ids):
        if eid in seen:
            continue
        seen.add(eid)
        entry = retrieved.get(eid)
        if entry is None:
            log.info("reflect citation dropped: memory_id %d not in retrieved set", eid)
            continue
        out.append(Citation(id=eid, title=entry.title))


    return out


async def _dispatch_search(
    index: RetrievalIndex,
    args: dict,
    retrieved: dict[int, MemoryEntry],
) -> dict:
    """Execute one search tool call. Mutates retrieved; returns JSON-serializable payload for the LLM.

    Capping k at 20 here rather than in the LLM's declaration so the server
    enforces the limit even if the model ignores the description.
    """
    query = args.get("query") or ""
    type_filter = args.get("type")
    k = int(args.get("k") or 5)
    if k > 20:
        k = 20

    # Validate type before hitting the index to give the LLM a clear error.
    if type_filter is not None and type_filter not in (
        "decision", "context", "lesson", "procedure"
    ):
        return {"error": f"invalid type: {type_filter!r}", "results": []}

    try:
        results: list[SearchResult] = await retrieval_search(
            index, query, k=k, type_filter=type_filter
        )
    except RuntimeError as e:
        return {"error": str(e), "results": []}

    payload = {
        "results": [
            {
                "entry_id": r.entry_id,
                "title": r.entry.title,
                "type": r.entry.type,
                "score": r.score,
                "body": r.entry.body,
                "created": r.entry.created,
                "modified": r.entry.modified,
            }
            for r in results
        ]
    }
    # Accumulate retrieved entries so _resolve_citations can validate ids.
    for r in results:
        retrieved[r.entry_id] = r.entry
    return payload


# ---------------------------------------------------------------------------
# Loop driver
# ---------------------------------------------------------------------------

async def run_reflect_agent(
    index: RetrievalIndex,
    question: str,
    context: str | None = None,
    *,
    on_trace: Callable[[ReflectTraceEvent], None] | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> ReflectResult:
    """Run the Gemini tool-calling reflection loop and return a cited briefing.

    Raises IterationCapExceeded if the model does not call "done" within
    max_iterations turns. Raises RuntimeError for API-key or client errors.
    No partial/best-effort answer is synthesized on overflow (fail-fast).
    """
    retrieved: dict[int, MemoryEntry] = {}

    # Build initial user message.
    user_text = f"# Question\n{question}"
    if context:
        user_text += (
            "\n\n# Caller background (framing only, NOT memory content)\n"
            f"{context}"
        )

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=user_text)])
    ]

    client = genai.Client(api_key=_api_key())
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=_TOOLS,
        temperature=0.0,

        # This is not rocket science, we can use lower thinking
        thinking_config=types.ThinkingConfig(thinking_level="minimal")
    )

    # Sync the index once before the loop; each retrieval_search call also
    # calls ensure_synced internally, but front-loading it avoids paying the
    # sync cost inside the first iteration's latency.
    await index.ensure_synced()

    for i in range(max_iterations):
        response = await client.aio.models.generate_content(
            model=_model(),
            contents=contents,
            config=config,
        )

        # Append the model turn so the conversation is coherent next iteration.
        assistant_content = response.candidates[0].content
        contents.append(assistant_content)

        parts = assistant_content.parts or []
        function_calls = [p for p in parts if p.function_call is not None]

        if not function_calls:
            # Model emitted text only -- nudge it back to tool use.
            log.info("reflect iter %d: no function call emitted, nudging", i + 1)
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Your last turn emitted prose but no tool call. This "
                    "loop only progresses through tool calls -- free "
                    "text is not shown to the caller and is not stored. "
                    "If you need more evidence, call `search`. If your "
                    "draft is complete and every claim is backed by a "
                    "retrieved entry, call `done`. Do not ask "
                    "clarifying questions; no one will answer."
                ))],
            ))
            continue

        # Process each function call in this turn. "done" terminates immediately.
        function_responses: list[types.Part] = []
        done_args: dict | None = None

        for part in function_calls:
            fc = part.function_call
            name = fc.name
            args = dict(fc.args) if fc.args else {}

            if name == "done":
                done_args = args
                break

            if name == "search":
                payload = await _dispatch_search(index, args, retrieved)
                result_count = len(payload.get("results", []))
                if on_trace is not None:
                    on_trace(ReflectTraceEvent(
                        iteration=i + 1,
                        tool="search",
                        args=args,
                        result_count=result_count,
                    ))
                function_responses.append(types.Part(
                    function_response=types.FunctionResponse(
                        name="search",
                        response=payload,
                    )
                ))
            else:
                log.warning("reflect iter %d: unknown tool %r", i + 1, name)
                function_responses.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=name,
                        response={"error": f"unknown tool: {name}"},
                    )
                ))

        if done_args is not None:
            if on_trace is not None:
                on_trace(ReflectTraceEvent(
                    iteration=i + 1,
                    tool="done",
                    args=done_args,
                ))
            answer = done_args.get("answer") or ""
            raw_ids = done_args.get("memory_ids") or []
            # Coerce to int defensively in case the model emits floats.
            memory_ids = [int(x) for x in raw_ids]
            citations = _resolve_citations(memory_ids, retrieved)
            return ReflectResult(
                answer=answer,
                citations=citations,
                iterations=i + 1,
            )

        # Append search responses as a single user turn.
        if function_responses:
            contents.append(types.Content(role="user", parts=function_responses))

    raise IterationCapExceeded(iterations=max_iterations)

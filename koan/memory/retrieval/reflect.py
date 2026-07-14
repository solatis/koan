# LLM-driven reflection loop over project memory.
#
# run_reflect_agent runs a single-conversation tool-calling loop that searches
# memory as many times as needed, then returns a cited briefing. Uses
# pydantic-ai with any chat provider via the adapter.
# Model selection is driven by explicit `model` (reflect LLM) and `embed` (embedding) ModelSpec parameters
# passed to `run_reflect_agent`; no module global is read.
# Evaluation is handled through evals/, not unit mocks.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    PartStartEvent,
    PartDeltaEvent,
    TextPart,
    ThinkingPart,
    TextPartDelta,
    ThinkingPartDelta,
)

from ..types import MemoryEntry
from ..timestamps import iso_to_ms
from ...logger import get_logger
from .backend import search as retrieval_search
from .index import RetrievalIndex
from .types import SearchResult

from ...types import ModelSpec
log = get_logger("memory.retrieval.reflect")

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

4. Select citations, then call `cite`. For EACH claim in your draft,
   name which retrieved entry backs it. An entry backs a claim only
   if removing that entry would force you to drop the claim. Entries
   you saw in search results but did not rely on are NOT citations --
   exclude them from `memory_ids`. Citing seen-but-unused entries is
   the most common failure mode of this agent; actively filter. Then
   call `cite(memory_ids)` with the backing entry ids.

5. Write the briefing as your final output. 300-500 tokens of markdown
   prose. Open with the most load-bearing finding. Use concrete names
   and dates from the entries. Close by naming what the memory does
   NOT cover about the question -- omissions are data.

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
  Session tokens live in Redis 7.x.           -> backed by #12
  "JWT-in-cookies was rejected on 2026-02-10."  -> backed by #18
  "A prior incident hardcoded tokens in the
   compose file; watch for this in IaC diffs."  -> backed by #24

Memory entries #21 (auth DB migration) and #31 (ruff config) were
retrieved but do not back any claim in this briefing. Correct
citation list is [12, 18, 24]. A drifted list would be
[12, 18, 21, 24, 31] -- do not do this. Call `cite([12, 18, 24])`,
then write the briefing as your final text output.

## Sparse results

If your searches return little that is on-topic, do not pad the
briefing with speculation to hit the token target. Write a shorter
briefing that names the gap. "Memory does not cover X" is a valid
finding; inventing X is not.

## Termination

Single-turn, non-conversational. Do not ask follow-up questions; no
one will answer. Do not offer alternatives or next steps. Call `cite`
with your backing entry ids, then write the briefing as your final
text output. The loop is capped at 10 tool calls total -- exceeding
the cap returns no answer at all, so spend calls on evidence, not
deliberation.
"""

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class ReflectTraceEvent:
    """A single trace event from the reflect subagent's internal loop.

    Kinds:
        search_start   -- emitted before _dispatch_search; signals a search
            is running (two-phase lifecycle with ``search``).
        search         -- emitted after _dispatch_search completes; carries
            result_count. The inline projection fold matches this to the
            last ``search_start``-derived running entry.
        thinking_delta -- raw thinking content delta from PartStart/PartDelta
            events. The inline callback forwards these as
            ``reflect_inline_trace`` events with kind ``thinking_delta`` for
            accumulation in the fold.
        text           -- raw text content delta; the inline callback
            forwards these as ``reflect_inline_trace`` events with kind
            ``text`` for answer streaming.
    """

    iteration: int
    kind: Literal["search_start", "search", "thinking_delta", "text"]
    query: str = ""
    type_filter: str = ""
    result_count: int | None = None   # populated for search after dispatch
    delta: str = ""                   # populated for thinking/text


@dataclass
class Citation:
    id: int
    title: str
    type: str
    modified_ms: int


@dataclass
class ReflectResult:
    answer: str
    citations: list[Citation]
    iterations: int


class IterationCapExceeded(Exception):
    def __init__(self, iterations: int) -> None:
        super().__init__(
            f"reflect loop exceeded {iterations} iterations without producing a briefing"
        )
        self.iterations = iterations




# ---------------------------------------------------------------------------
# Dependencies injected into the agent
# ---------------------------------------------------------------------------

@dataclass
class _Deps:
    """Dependencies injected into the reflect agent's tools and loop.

    Fields:
        index: The retrieval index backing search calls.
        retrieved: Accumulates entries from all search calls; used by
            _resolve_citations to validate cited ids.
        on_trace: Optional callback for streaming trace events to the
            projection layer (inline reflect path).
        iteration: Current model-request count, incremented per turn.
        cited_ids: Set by the ``cite`` tool call; the backing entry ids
            for the forthcoming briefing. None if ``cite`` was never
            called (citations default to empty).
        accumulated_answer: Text deltas from the model's terminal text
            output, accumulated during streaming for ReflectResult.answer.
        embedding: Embedding ModelSpec for retrieval vector search.
    """
    index: RetrievalIndex
    retrieved: dict[int, MemoryEntry] = field(default_factory=dict)
    on_trace: Callable[[ReflectTraceEvent], None] | None = None
    iteration: int = 0
    cited_ids: list[int] | None = None
    accumulated_answer: str = ""
    embedding: ModelSpec | None = None


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

# Agent is constructed lazily inside run_reflect_agent so the model spec
# is resolved at call time via the explicit MemoryModels bundle.

def _build_agent(model: ModelSpec) -> Agent[_Deps, None]:
    """Build the reflect agent using the explicit `model` ModelSpec (the reflect LLM).

    The model/key arrive via the explicit model parameter; no module global
    is read. Model settings (thinking + caching, baked into the spec at flatten
    time) come from the spec via build_model_settings. Temperature is left to
    the provider/PydanticAI default -- forcing 0.0 alongside thinking/adaptive
    mode causes an Anthropic 400.
    """
    # Late-binding import so monkeypatching adapter attributes in tests is observed
    # at call time (same pattern used throughout the agent layer).
    from ...agents.adapter import build_model, build_model_settings

    # Terminal text output IS the briefing -- no TextOutput wrapper.
    # The model writes the briefing as plain text after calling `cite`.
    built_model = build_model(model, api_key=model.api_key, region=None, base_url=model.base_url)
    agent: Agent[_Deps, str] = Agent(
        model=built_model,
        system_prompt=SYSTEM_PROMPT,
        model_settings=build_model_settings(model),
        output_type=str,
    )

    @agent.tool(name="search")
    async def search_tool(
        ctx: RunContext[_Deps],
        query: str,
        type: str | None = None,
        k: int = 5,
    ) -> dict:
        """Hybrid semantic + BM25 search over the project memory store.

        Returns an array of entries; each entry has fields: entry_id (int,
        use this in memory_ids), title, type, score, body (full markdown
        content), created, modified. Rank is by score. Call this multiple
        times with decomposed queries to cover different facets.

        Args:
            query: A single entity or concept -- NOT the user's full question.
                Good: 'session token storage', 'Auth0 integration', 'PostgreSQL
                migration'. Bad: 'how does auth work', 'tell me about the
                database'. Run 3-5 such queries per question.
            type: Optional filter. decision = choices made; context = stable
                project/team/infra facts; lesson = past mistakes; procedure =
                actionable rules. Set it when scoped to one type; omit to scan
                all types.
            k: Number of entries to return. Default 5 is almost always right.
                Raise to 10-20 only for broad recall. Hard cap: 20.
        """
        args = {"query": query, "type": type, "k": k}
        # Pre-dispatch trace enables two-phase search (running -> done) in the
        # inline projection: the fold appends a running entry on search_start
        # and updates it with resultCount when the post-dispatch search trace
        # arrives.
        if ctx.deps.on_trace is not None:
            ctx.deps.on_trace(ReflectTraceEvent(
                iteration=ctx.deps.iteration,
                kind="search_start",
                query=query,
                type_filter=type or "",
            ))
        payload = await _dispatch_search(ctx.deps.index, args, ctx.deps.retrieved, ctx.deps.embedding)
        result_count = len(payload.get("results", []))
        if ctx.deps.on_trace is not None:
            ctx.deps.on_trace(ReflectTraceEvent(
                iteration=ctx.deps.iteration,
                kind="search",
                query=query,
                type_filter=type or "",
                result_count=result_count,
            ))
        return payload

    @agent.tool(name="cite")
    async def cite_tool(
        ctx: RunContext[_Deps],
        memory_ids: list[int],
    ) -> str:
        """Record which retrieved entries back the forthcoming briefing.

        Call this immediately before writing the briefing text. Every
        claim in your briefing must be backed by a specific entry returned
        by a prior search call in this conversation.

        Args:
            memory_ids: Entry IDs that back specific claims in the briefing.
                Include an id iff removing that entry from your evidence
                would force you to drop some claim. Do NOT include entries
                that appeared in search results but were not relied on --
                that mistake (citing seen entries rather than used entries)
                is the primary failure mode. Dedupe; order does not matter.
        """
        ctx.deps.cited_ids = memory_ids
        return "cited"

    return agent


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable: take plain data, no LLM involvement)
# ---------------------------------------------------------------------------

def _resolve_citations(
    memory_ids: list[int],
    retrieved: dict[int, MemoryEntry],
) -> list[Citation]:
    """Filter memory_ids by membership in retrieved set, preserve order, dedupe.

    Drops any id not present in the retrieved set (hallucination guard) and
    logs each dropped id at INFO level. Returns Citation objects with type and
    modified_ms populated from the retrieved entry.
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
        out.append(Citation(
            id=eid,
            title=entry.title,
            type=entry.type,
            modified_ms=iso_to_ms(entry.modified),
        ))

    return out


async def _dispatch_search(
    index: RetrievalIndex,
    args: dict,
    retrieved: dict[int, MemoryEntry],
    model: ModelSpec | None,
) -> dict:
    """Execute one search tool call. Mutates retrieved; returns JSON-serializable payload for the LLM.

    The embedding model/key arrive via the explicit model parameter.
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
            index, query, model, k=k, type_filter=type_filter
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
    model: ModelSpec,
    embed: ModelSpec,
    question: str,
    context: str | None = None,
    *,
    on_trace: Callable[[ReflectTraceEvent], None] | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> ReflectResult:
    """Run the pydantic-ai tool-calling reflection loop and return a cited briefing.

    The agent searches memory, calls `cite(memory_ids)` to record backing
    entry ids, then writes the briefing as terminal text output. The loop
    exhausts naturally when the model produces text without tool calls
    (PydanticAI's native End condition). Text deltas are accumulated into
    ``deps.accumulated_answer`` for the returned ``ReflectResult.answer``.

    model (reflect LLM) and embed (embedding) ModelSpecs arrive via explicit
    parameters; the caller is responsible for resolving them before calling.
    Raises IterationCapExceeded if the model does not produce terminal text
    within max_iterations model-request turns. No partial/best-effort answer
    is synthesized on overflow.
    """
    from ...agents.adapter import build_usage_limits

    # Sync the index once before the loop; each retrieval_search call also
    # calls ensure_synced internally, but front-loading it avoids paying the
    # sync cost inside the first iteration's latency.
    await index.ensure_synced(embed)

    user_text = f"# Question\n{question}"
    if context:
        user_text += (
            "\n\n# Caller background (framing only, NOT memory content)\n"
            f"{context}"
        )

    deps = _Deps(index=index, on_trace=on_trace, embedding=embed)
    agent = _build_agent(model)
    model_request_count = 0

    async with agent.iter(user_text, deps=deps, usage_limits=build_usage_limits()) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                model_request_count += 1
                deps.iteration = model_request_count
                async with node.stream(run.ctx) as stream:
                    async for ev in stream:
                        if on_trace is None:
                            continue
                        if isinstance(ev, PartStartEvent):
                            if isinstance(ev.part, ThinkingPart) and ev.part.content:
                                on_trace(ReflectTraceEvent(
                                    iteration=model_request_count,
                                    kind="thinking_delta",
                                    delta=ev.part.content,
                                ))
                            elif isinstance(ev.part, TextPart) and ev.part.content:
                                # Terminal text output IS the briefing --
                                # accumulate for ReflectResult.answer.
                                deps.accumulated_answer += ev.part.content
                                on_trace(ReflectTraceEvent(
                                    iteration=model_request_count,
                                    kind="text",
                                    delta=ev.part.content,
                                ))
                        elif isinstance(ev, PartDeltaEvent):
                            if isinstance(ev.delta, ThinkingPartDelta) and ev.delta.content_delta:
                                on_trace(ReflectTraceEvent(
                                    iteration=model_request_count,
                                    kind="thinking_delta",
                                    delta=ev.delta.content_delta,
                                ))
                            elif isinstance(ev.delta, TextPartDelta) and ev.delta.content_delta:
                                # Terminal text output IS the briefing --
                                # accumulate for ReflectResult.answer.
                                deps.accumulated_answer += ev.delta.content_delta
                                on_trace(ReflectTraceEvent(
                                    iteration=model_request_count,
                                    kind="text",
                                    delta=ev.delta.content_delta,
                                ))
                if model_request_count >= max_iterations:
                    raise IterationCapExceeded(iterations=max_iterations)

    # The loop exhausts naturally when the model produces terminal text
    # output (no tool calls). No explicit End-node check needed.

    # Extract cited_ids from deps (set by cite_tool); fall back to
    # extracting from run.all_messages() if cite was called but deps
    # wasn't set (defensive -- shouldn't happen in practice).
    memory_ids: list[int] = []
    if deps.cited_ids is not None:
        memory_ids = [int(x) for x in deps.cited_ids]
    else:
        try:
            for msg in run.all_messages():
                for part in getattr(msg, "parts", []):
                    tool_name = getattr(part, "tool_name", None)
                    if tool_name == "cite":
                        args = getattr(part, "args", None)
                        if isinstance(args, str):
                            import json as _json
                            args = _json.loads(args)
                        if isinstance(args, dict):
                            ids = args.get("memory_ids", [])
                            if ids:
                                memory_ids = [int(x) for x in ids]
        except Exception:
            # run.all_messages() may be inaccessible after the async
            # with block exits; default to empty citations.
            pass

    citations = _resolve_citations(memory_ids, deps.retrieved)
    return ReflectResult(
        answer=deps.accumulated_answer,
        citations=citations,
        iterations=model_request_count,
    )

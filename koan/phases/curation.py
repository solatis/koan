# Curation phase -- 2-step workflow.
#
# The curation phase has one job: write project memory. It is invoked from
# two entry points, distinguished only by the directive injected via
# ctx.phase_instructions:
#
#   - postmortem: source = the orchestrator's transcript (no scouts, no
#     codebase reads, no questions).
#   - standalone: source = the user's <task> + existing memory + the
#     codebase. May dispatch scouts and ask questions per directive.
#
# The static prompts below are directive-agnostic. They reference "your
# directive" without hardcoding the entry point. Variation lives in the
# directive layer (koan/lib/workflows.py).
#
# Step layout (collapsed from 3 -> 2 because the orchestrator was skipping
# the meaty step entirely; named after their primary tool effect to make
# tool-call elision impossible):
#
#   1 (Inventory) -- koan_memory_status + gather source + classify candidates
#   2 (Memorize)  -- yield -> koan_memorize / koan_forget loop, then verify
#
# The screenshots from the previous run showed the orchestrator confusing
# "Survey" with intake-style exploration and reaching "phase complete"
# without ever calling koan_memorize. The fix: give every step a
# <workflow_shape> / <goal> / <tools_this_step> header that names the
# orchestrator's position, the phase-level success criterion, and the
# specific tools to call this step. Re-read at every step so the structure
# is visible at the moment of use.

from __future__ import annotations

from . import PhaseContext, StepGuidance

ROLE = "orchestrator"
SCOPE = "general"
TOTAL_STEPS = 2

STEP_NAMES: dict[int, str] = {
    1: "Inventory",
    2: "Memorize",
}


# -- System prompt -------------------------------------------------------------
# Injected at the top of step 1. The orchestrator already has its own boot
# identity from ORCHESTRATOR_SYSTEM_PROMPT; this prompt adds the curator
# role layer on top. It does not redeclare the orchestrator identity.

SYSTEM_PROMPT = (
    "You are now operating as the project's knowledge curator. Your job is\n"
    "to maintain a small, high-quality memory of decisions, context, lessons,\n"
    "and procedures that helps AI coding agents work effectively across\n"
    "workflow runs.\n"
    "\n"
    "## Structural invariant\n"
    "\n"
    "You propose, the user approves, then you write. Every memory mutation\n"
    "(create, update, delete) must be presented to the user via `koan_yield`\n"
    "and explicitly approved before you call a write tool. There are no\n"
    "silent writes.\n"
    "\n"
    "## Tools\n"
    "\n"
    "Three MCP tools handle koan memory operations:\n"
    "\n"
    "- `koan_memory_status` -- orientation. Returns the project summary and\n"
    "  a flat listing of all entries (id, title, type, dates). Triggers\n"
    "  just-in-time regeneration of summary.md if entries changed since the\n"
    "  last summary. Call this first in step 1 and again at the end of\n"
    "  step 2 to verify your writes.\n"
    "- `koan_memorize` -- create or update an entry. Omit `entry_id` to\n"
    "  create; pass it to update. Sets `created` / `modified` timestamps\n"
    "  automatically and assigns the next sequence number for new entries.\n"
    "- `koan_forget` -- delete an entry by `entry_id`. Git preserves the\n"
    "  history of removed entries.\n"
    "\n"
    "## Reads vs. writes -- the asymmetry\n"
    "\n"
    "Reading and writing memory follow different rules. Both are sanctioned;\n"
    "they just use different paths.\n"
    "\n"
    "**Reading individual entries: native filesystem.**\n"
    "Memory entries are plain markdown at `.koan/memory/NNNN-*.md`. Read\n"
    "them directly with your standard file-reading tools whenever you need\n"
    "to compare a candidate against an existing entry, check for overlap,\n"
    "or verify a fact before classifying. This is the intended\n"
    "duplicate-detection path -- the listing from `koan_memory_status`\n"
    "gives you titles only, so direct reads are how you check bodies.\n"
    "\n"
    "**Reading the summary or the listing: koan_memory_status.**\n"
    "The project summary and the entry listing come from\n"
    "`koan_memory_status`, not from parsing files. The tool may regenerate\n"
    "summary.md under your feet; do not cache or parse it directly.\n"
    "\n"
    "**Writes: koan_memorize / koan_forget ONLY.**\n"
    "Do NOT write or delete files under `.koan/` directly. The write tools\n"
    "manage sequence-number assignment, timestamps, summary staleness\n"
    "tracking, and (in the upcoming review-gate feature) human approval.\n"
    "Bypassing them desyncs your view of memory from koan's index.\n"
    "\n"
    "## The coding agent's own memory (separate system)\n"
    "\n"
    "The coding agent running this orchestration (Claude Code, Cursor,\n"
    "Codex, etc.) may have its own memory at paths like CLAUDE.md,\n"
    "AGENTS.md, `.claude/projects/*/memory/`, `.cursor/`, etc. Treat these\n"
    "as a SEPARATE system from koan memory:\n"
    "\n"
    "- They are READ-ONLY input. Consult them during step 1 inventory as\n"
    "  one source of project context, alongside the directive and task.\n"
    "  They often contain useful prior knowledge.\n"
    "- You do NOT write to them. They belong to the coding agent.\n"
    "- They are NOT koan memory. The only koan memory is what\n"
    "  `koan_memory_status` returns and what lives at `.koan/memory/`.\n"
    "\n"
    "When a fact appears in both the coding agent's memory and koan\n"
    "memory, trust the koan version -- it went through curation review.\n"
    "\n"
    "## Memory types\n"
    "\n"
    "- **decision**  -- architectural choices with rationale and rejected\n"
    "                   alternatives. Why is the project the way it is?\n"
    "- **context**   -- project facts not derivable from code: team,\n"
    "                   infrastructure, external services, business rules.\n"
    "- **lesson**    -- things that went wrong and the root cause. Not\n"
    "                   symptoms.\n"
    "- **procedure** -- behavioral rules for agents. Checkable conditions\n"
    "                   and concrete actions. Often paired with a lesson.\n"
    "\n"
    "## Picking the type for a candidate\n"
    "\n"
    "The definitions above say what each type IS. This tree says how to\n"
    "PICK one for a given candidate. Walk the four questions in order;\n"
    "the FIRST match wins.\n"
    "\n"
    "| # | Question                                              | If YES    |\n"
    "|---|-------------------------------------------------------|-----------|\n"
    "| 1 | Does this entry name a choice between alternatives,   | decision  |\n"
    "|   | with rationale (why X over Y)?                        |           |\n"
    "| 2 | Did the user correct the agent during this run       | lesson    |\n"
    "|   | (agent first thought X, but the right answer was Y), |           |\n"
    "|   | OR does this entry record a thing that went wrong    |           |\n"
    "|   | with an identified root cause?                        |           |\n"
    "| 3 | Does this entry tell a future agent what to do       | procedure |\n"
    "|   | under condition X (a behavioral rule)?                |           |\n"
    "| 4 | Is this a stable fact about the project (team,       | context   |\n"
    "|   | infrastructure, conventions) that does not tell       |           |\n"
    "|   | anyone what to do?                                    |           |\n"
    "\n"
    "If none match, the candidate is probably not memory-worthy -- drop\n"
    "it. Candidates can match multiple rows; first-match-wins means:\n"
    "\n"
    "- An actionable rule that came from a specific corrected mistake\n"
    "  stays as a lesson (question 2 fires before question 3). The\n"
    "  generalized procedure can be a follow-up entry, linked via\n"
    "  `related`.\n"
    "- An architectural choice with rationale is a decision even when\n"
    "  it implies a rule for future agents (question 1 fires before\n"
    "  question 3).\n"
    "\n"
    "## Classification schema\n"
    "\n"
    "Before drafting any candidate, classify it against existing memory:\n"
    "\n"
    "- **ADD**       -- no existing entry covers this. Draft a new entry.\n"
    "- **UPDATE**    -- an existing entry covers this but needs revision.\n"
    "                   Draft the revision; pass `entry_id` to `koan_memorize`.\n"
    "- **NOOP**      -- already adequately captured. Skip.\n"
    "- **DEPRECATE** -- this knowledge makes an existing entry obsolete.\n"
    "                   Propose removal via `koan_forget`. (The action label\n"
    "                   is DEPRECATE; the tool is `koan_forget` -- they\n"
    "                   refer to the same operation.)\n"
    "\n"
    "## Writing discipline (high-level)\n"
    "\n"
    "Every entry is 100-500 tokens of **temporally grounded, attributed,\n"
    "event-style** prose -- a historical fact that stays true regardless\n"
    "of when it is read. The full rules, two contrastive bad/good\n"
    "examples, and a 5-item self-validation checklist appear in step 2\n"
    "(Memorize), rendered at the drafting moment. Do NOT skim the step 2\n"
    "examples -- your default register for technical content is timeless\n"
    "documentation prose, and the examples are the only thing that\n"
    "overrides that default.\n"
    "\n"
    "Use the `related` field (filenames like `0002-infrastructure.md`)\n"
    "to link a lesson to its derived procedure, or a decision to its\n"
    "motivating context.\n"
    "\n"
    "## What not to capture\n"
    "\n"
    "- Implementation details derivable from reading the code, EXCEPT:\n"
    "  - The **rationale and rejected alternatives** behind architectural\n"
    "    decisions. These are NOT in code -- they are in the heads of the\n"
    "    people who made the choice, and in the conversations that\n"
    "    surfaced the choice. Capture them.\n"
    "  - The **lessons from prior workflows** -- corrected mistakes,\n"
    "    surprises, root causes of failures. These are not in code;\n"
    "    they are history. Capture them.\n"
    "- Temporary implementation details that will not matter next week.\n"
    "- Opinions without grounding in project experience.\n"
    "- Anything already adequately captured (use NOOP, not a duplicate).\n"
)


# -- Step header (rendered at the top of every step) --------------------------
# Re2-inspired structural repetition: every step shows the orchestrator its
# position, the phase-level goal, and the specific tools to call this step.
# This kills the "wait, are we in intake?" confusion seen in the screenshots.

def _workflow_shape_block(current_step: int) -> list[str]:
    you_are_here_1 = "(<-- YOU ARE HERE)" if current_step == 1 else ""
    you_are_here_2 = "(<-- YOU ARE HERE)" if current_step == 2 else ""
    return [
        "<workflow_shape>",
        "The curation workflow has exactly ONE phase: curation.",
        "That phase has 2 steps:",
        f"  step 1 -- Inventory   (identify candidates)            {you_are_here_1}",
        f"  step 2 -- Memorize    (write entries via koan_memorize) {you_are_here_2}",
        "When step 2 completes, the workflow is done. There is no further phase.",
        "Do NOT read koan source code to figure this out -- this block is the",
        "authoritative answer.",
        "</workflow_shape>",
    ]


def _goal_block() -> list[str]:
    return [
        "<goal>",
        "By the end of step 2 you will have called `koan_memorize` (and",
        "possibly `koan_forget`) one or more times to write user-approved",
        "memory entries. That is the only success criterion for this phase.",
        "Step 1 is preparation; step 2 is where the writes happen.",
        "</goal>",
    ]


def _tools_this_step_block(current_step: int) -> list[str]:
    if current_step == 1:
        return [
            "<tools_this_step>",
            "1. `koan_memory_status` -- call FIRST. Loads the existing memory view.",
            "2. Direct file reads of `.koan/memory/NNNN-*.md` -- compare candidates",
            "   against existing entries when classifying.",
            "3. Source-gathering tools authorized by your directive (scouts, doc",
            "   reads, `koan_ask_question`, walking your conversation history).",
            "4. `koan_complete_step` -- LAST, after you have a candidate list.",
            "</tools_this_step>",
        ]
    if current_step == 2:
        return [
            "<tools_this_step>",
            "Writing discipline, two contrastive examples, and a 5-item",
            "draft-quality checklist appear in this step's body below.",
            "Read them BEFORE drafting your first candidate.",
            "",
            "1. `koan_yield`         -- present each batch of proposals to the user.",
            "2. `koan_memorize`      -- write approved ADD / UPDATE entries.",
            "3. `koan_forget`        -- delete approved DEPRECATE entries.",
            "4. `koan_memory_status` -- call ONCE at the end to verify your writes.",
            "5. `koan_complete_step` -- LAST, after the anticipatory check passes.",
            "</tools_this_step>",
        ]
    return []


def _header(current_step: int) -> list[str]:
    return (
        _workflow_shape_block(current_step)
        + [""]
        + _goal_block()
        + [""]
        + _tools_this_step_block(current_step)
        + [""]
    )


# -- Step 1: Inventory ---------------------------------------------------------

def _step_1_inventory(ctx: PhaseContext) -> StepGuidance:
    directive = ctx.phase_instructions or (
        "No directive provided. Default to the standalone posture: read the\n"
        "<task> block, check existing memory, and infer the mode."
    )

    # The <task> block is only meaningful when there is a user task. In the
    # postmortem path the task_description is whatever the parent workflow
    # was about, not a curation directive -- the postmortem directive tells
    # the orchestrator to ignore it and use the transcript instead.
    task_block = (
        ctx.task_description.strip()
        if ctx.task_description and ctx.task_description.strip()
        else "(no user task -- see your directive for where the source lives)"
    )

    instructions = _header(1) + [
        "## Step 1: Inventory",
        "",
        "Identify the candidates that step 2 will write. By the end of this",
        "step you will have a numbered candidate list ready for the memorize",
        "loop. Nothing is written in this step.",
        "",
        "## Input blocks",
        "",
        "<directive>",
        directive,
        "</directive>",
        "",
        "<task>",
        task_block,
        "</task>",
        "",
        "## Procedure",
        "",
        "1. Call `koan_memory_status` FIRST. This is your only sanctioned",
        "   view of the project summary and entry listing. Read both.",
        "",
        "2. Read your <directive>. It tells you where the source material",
        "   lives (transcript / docs / scouts / interview) and what",
        "   source-gathering moves you are authorized to make.",
        "",
        "3. If <task> is non-empty, read it. The directive will tell you",
        "   whether to use it as your primary anchor or to ignore it.",
        "",
        "4. Gather source material per the directive's posture. Examples:",
        "   - postmortem  -> walk your conversation history above",
        "   - review      -> read suspect entries directly from",
        "                    `.koan/memory/`, dispatch scouts to verify",
        "   - document    -> read the doc the user pointed at, dispatch",
        "                    scouts for broad sources",
        "   - bootstrap   -> dispatch scouts, read README/AGENTS.md/CLAUDE.md,",
        "                    interview the user via `koan_ask_question`",
        "",
        "5. Consult the coding agent's own memory if it exists",
        "   (CLAUDE.md, AGENTS.md, `.claude/projects/*/memory/`, etc.).",
        "   It is useful prior knowledge about the project. It is NOT",
        "   koan memory -- treat it as read-only input only.",
        "",
        "6. Build a numbered candidate list. For each candidate note:",
        "   - type           -- assign using the 4-question discrimination",
        "                       tree in the system prompt above (\"Picking",
        "                       the type for a candidate\"). Walk the four",
        "                       questions in order; first match wins. If",
        "                       none match, drop the candidate as not",
        "                       memory-worthy.",
        "   - title          (one line)",
        "   - classification (ADD / UPDATE / NOOP / DEPRECATE)",
        "   - entry_id       (only for UPDATE / DEPRECATE)",
        "   When a candidate is close to an existing topic, read the suspect",
        "   entries directly from `.koan/memory/` before classifying.",
        "",
        "## End-of-step output",
        "",
        "A numbered candidate list. This becomes the input to step 2's",
        "memorize loop.",
        "",
        "Do NOT call `koan_complete_step` until you have at least one",
        "candidate with classification ADD, UPDATE, or DEPRECATE.",
        "Exception: if the source genuinely contains no novel knowledge,",
        "state that explicitly (\"all candidates were NOOPs because X\") and",
        "then complete the step.",
    ]
    return StepGuidance(title=STEP_NAMES[1], instructions=instructions)


# -- Step 2: Memorize ----------------------------------------------------------

def _step_2_memorize(ctx: PhaseContext) -> StepGuidance:
    instructions = _header(2) + [
        "## Step 2: Memorize",
        "",
        "This is the writing step. Your candidate list from step 1 becomes",
        "`koan_memorize` and `koan_forget` calls, gated by user approval",
        "via `koan_yield`.",
        "",
        "Read the writing discipline, contrastive examples, and the",
        "draft-quality checklist below BEFORE drafting your first",
        "candidate. The rules are rendered here, at the drafting moment,",
        "because verbal rules from the system prompt do not survive the",
        "distance to this step -- your default register for technical",
        "content is timeless documentation prose, which violates every",
        "rule. The examples are how you override that default.",
        "",
        "## Writing discipline (full rules)",
        "",
        "Every entry body obeys these five rules. Each rule has a",
        "corresponding check in the self-critique substep below.",
        "",
        "**1. Open with a named subsystem.** The first 1-3 sentences",
        "situate the entry by naming the specific subsystem, artifact,",
        "or decision it is about (examples: \"the session storage for",
        "the user-facing web service\", \"the deployment pipeline's cache",
        "layer\", \"the configuration loader\"). If the entry is about the",
        "project as a whole, the first sentence names the project",
        "explicitly. Vague openings (\"This system uses...\", \"The",
        "project enforces...\") hurt retrieval because embeddings have",
        "no specific anchor.",
        "",
        "**2. Temporally ground every claim.** Use absolute dates in",
        "YYYY-MM-DD form (\"On 2025-09-12, the team decided...\"). A year",
        "alone, or relative terms like \"recently\", \"currently\", \"at the",
        "moment\" fail. Temporal grounding turns every entry into a",
        "historical fact that stays true regardless of when it is read.",
        "",
        "**3. Attribute every claim to its source.** Name who said or",
        "discovered the fact: \"user stated\", \"the team decided\",",
        "\"post-mortem identified\", \"LLM inferred\", \"developer",
        "confirmed\", \"maintainer agreed\". User-stated facts carry higher",
        "trust than inferences; readers need to know which is which.",
        "",
        "**4. Event-style, past tense.** Describe what happened, not",
        "what is. \"We use Redis\" fails; \"On <date>, the team adopted",
        "Redis 7.2...\" passes. Forward-looking language (\"we will\",",
        "\"should\", \"must\") also fails unless embedded inside a past-",
        "tense attribution (\"On <date>, the team decided that the rule",
        "is to...\").",
        "",
        "**5. Name things concretely.** Use specific versions, file",
        "paths, tool names, table names, column names, environment",
        "variable names. \"The database\" fails; \"PostgreSQL 16.2\"",
        "passes. \"Some config\" fails; \"the BUILD_TARGET environment",
        "variable in deploy/production.env\" passes.",
        "",
        "## Contrastive examples",
        "",
        "These are general-purpose templates, not examples from koan",
        "itself. Study each bad/good pair and the explanation of what",
        "changed. The GOOD versions are the shape your drafts must",
        "take.",
        "",
        "<example type=\"decision-bad\">",
        "We use Redis for session storage because it's fast and reliable.",
        "</example>",
        "",
        "<example type=\"decision-good\">",
        "This entry documents the choice of session storage for the",
        "user-facing web service. On 2025-09-12, the team decided to",
        "adopt Redis 7.2 for session storage, replacing in-process",
        "Python dicts. Rationale: horizontal scaling required session",
        "state to live outside individual app workers, and the existing",
        "operational tooling already supported Redis. Alternatives",
        "rejected: Memcached (no built-in persistence, complicating",
        "session continuity across restarts), PostgreSQL session table",
        "(added 40-80 ms of latency to every request per the team's",
        "staging benchmarks). Decision surfaced during a post-mortem on",
        "a session-loss incident under load on 2025-09-08.",
        "</example>",
        "",
        "What changed between bad and good:",
        "",
        "- Bad opens with \"We use\" (timeless present); good opens by",
        "  naming the subsystem (\"session storage for the user-facing",
        "  web service\") and follows with a dated event.",
        "- Bad has no date; good anchors both the decision (2025-09-12)",
        "  and the motivating incident (2025-09-08).",
        "- Bad has no attribution; good attributes to \"the team\" and",
        "  names the surfacing context (a post-mortem).",
        "- Bad names nothing concretely; good names Redis 7.2, the",
        "  rejected alternatives, the specific latency numbers, and the",
        "  incident that drove the decision.",
        "- Bad would become stale if Redis is later replaced; good",
        "  remains true as a historical record forever.",
        "",
        "<example type=\"lesson-bad\">",
        "Don't forget to update the schema migration when adding new columns.",
        "</example>",
        "",
        "<example type=\"lesson-good\">",
        "This entry records a deployment failure in the user-management",
        "service. On 2025-11-03, a feature branch added a `last_seen_at`",
        "column to the users table at the ORM model level but omitted",
        "the corresponding Alembic migration file. The change passed",
        "local tests because the local test database used SQLite, which",
        "auto-creates columns from ORM model definitions. Staging",
        "deployment failed when PostgreSQL rejected inserts referencing",
        "the missing column. Root cause: the test harness used a",
        "different database engine than production, hiding schema drift",
        "at merge time. Correction applied on 2025-11-04: the team",
        "added a CI step that runs all Alembic migrations against an",
        "empty PostgreSQL instance before test suites execute, catching",
        "ORM/schema drift before merge.",
        "</example>",
        "",
        "What changed between bad and good:",
        "",
        "- Bad is a forward-looking instruction (\"don't forget\"); good",
        "  is an event record of a specific dated failure.",
        "- Bad has no root cause; good identifies it (test harness",
        "  used a different database than production).",
        "- Bad has no concrete artifacts; good names Alembic, SQLite,",
        "  PostgreSQL, `last_seen_at`, the users table, and the new CI",
        "  step.",
        "- Bad would become stale if the team switches migration tools;",
        "  good stays true as a dated historical record.",
        "",
        "## The per-batch loop (6 sub-operations, in order)",
        "",
        "For each batch of 3-5 candidates from your step 1 list, run",
        "these sub-operations IN ORDER. Each sub-operation produces a",
        "committed, VISIBLE output in your response before the next",
        "begins. Do not collapse substeps. Do not skip ahead. The",
        "committed-artifact structure is the load-bearing quality gate --",
        "collapsing it lets the model sandbag drafts to manufacture",
        "obvious improvements at the revise step without actually",
        "improving anything.",
        "",
        "### A. Draft",
        "",
        "Write each non-NOOP candidate as a complete entry, modeled on",
        "the GOOD examples above. Include type, title, body, related,",
        "and (for UPDATE / DEPRECATE) entry_id.",
        "",
        "Output all drafts for this batch as a visible list BEFORE",
        "moving to substep B. You must commit to the drafts as-is",
        "before self-critiquing them.",
        "",
        "### B. Self-critique",
        "",
        "For each draft produced in substep A, run the 5-item draft-",
        "quality checklist below. Output the checklist result PER",
        "DRAFT in this exact format:",
        "",
        "    Draft 1 ({title}):",
        "      1. Opens with named subsystem: PASS / FAIL",
        "      2. Contains absolute date:     PASS / FAIL",
        "      3. Contains attribution:       PASS / FAIL",
        "      4. Event-style, past tense:    PASS / FAIL",
        "      5. Concrete naming:            PASS / FAIL",
        "",
        "    Draft 2 ({title}):",
        "      ...",
        "",
        "Do not skip this substep. Do not merge it into substep A or C.",
        "The explicit checklist output is the committed artifact that",
        "prevents simulated refinement -- if substep B is absent, the",
        "whole quality gate collapses.",
        "",
        "### C. Revise",
        "",
        "For every draft with any FAIL in its checklist, rewrite the",
        "entry completely. Do not patch in place -- rewrite it, using",
        "the GOOD example template as the target form. After each",
        "rewrite, re-run the 5-item checklist on the revised draft.",
        "Loop until all 5 items PASS for all drafts in the batch.",
        "",
        "You MAY NOT proceed to substep D (Yield) while any draft in",
        "this batch has an outstanding FAIL.",
        "",
        "### D. Yield",
        "",
        "Call `koan_yield` with the final (all-PASS) proposals as",
        "markdown plus these structured suggestions:",
        "",
        '   - {id: "approve", label: "Approve all",          command: "Approve all entries in this batch"}',
        '   - {id: "skip",    label: "Skip all",             command: "Skip this batch"}',
        '   - {id: "review",  label: "Review individually",  command: "Let me review each entry"}',
        "",
        "### E. Apply",
        "",
        "Apply approved changes:",
        "- ADD       -> `koan_memorize` (no `entry_id`)",
        "- UPDATE    -> `koan_memorize` (with `entry_id`)",
        "- DEPRECATE -> `koan_forget`   (with `entry_id`)",
        "- NOOP      -> nothing",
        "",
        "### F. Cross off",
        "",
        "Cross items off your candidate list and loop back to substep",
        "A with the next batch. Continue until the list is empty or",
        "the user tells you to stop.",
        "",
        "## Draft-quality checklist (schema for substep B)",
        "",
        "For each draft, verify all 5 items. Any FAIL means the draft",
        "cannot be yielded -- it must go back through substep C.",
        "",
        "**1. Opens with a named subsystem.**",
        "First sentence names the specific subsystem, decision, or",
        "artifact this entry is about. If the entry is about the",
        "project as a whole, the first sentence names the project",
        "explicitly. Openings like \"This system...\", \"The project...\",",
        "or a rule statement with no subject FAIL this check.",
        "",
        "**2. Contains at least one absolute date.**",
        "Body has one or more dates in YYYY-MM-DD form anchoring an",
        "event. A year alone, or words like \"recently\", \"currently\",",
        "\"at the moment\" FAIL.",
        "",
        "**3. Contains an attribution phrase.**",
        "Body explicitly states who said or discovered each claim:",
        "\"user stated\", \"the team decided\", \"post-mortem identified\",",
        "\"LLM inferred\", \"developer confirmed\", \"maintainer agreed\".",
        "Anonymous declarations (\"it was decided that...\" without a",
        "subject) FAIL.",
        "",
        "**4. Event-style, past tense.**",
        "Body describes events that happened (\"On <date>, X did Y\"),",
        "not timeless facts (\"We use X\"). Present-tense \"is\"",
        "statements about how things currently work FAIL. Forward-",
        "looking language (\"we will\", \"should\", \"must\") also FAILS",
        "unless embedded inside a past-tense attribution.",
        "",
        "**5. Concrete naming.**",
        "Body names specific entities: versions, file paths, tool",
        "names, table names, column names, environment variable names.",
        "\"The database\" FAILS; \"PostgreSQL 16.2\" passes. \"Some config\"",
        "FAILS; \"the BUILD_TARGET environment variable in",
        "deploy/production.env\" passes.",
        "",
        "## Anticipatory tool-call check (BEFORE the wrap-up)",
        "",
        "After all batches have been processed, before you call",
        "`koan_complete_step`, verify:",
        "",
        "- Did you call `koan_memorize` at least once for the ADD /",
        "  UPDATE items on your step 1 candidate list?",
        "- Did you call `koan_forget` for any DEPRECATE items?",
        "",
        "If NO and your step 1 list was non-empty: you have not done",
        "the work of this phase. Loop back to substep A with the",
        "remaining candidates. Do not advance to the wrap-up with zero",
        "writes.",
        "",
        "If your step 1 list was explicitly empty (\"all candidates",
        "were NOOPs because X\"), zero writes is correct -- continue",
        "to wrap-up.",
        "",
        "## Wrap-up",
        "",
        "1. Call `koan_memory_status` once. Triggers just-in-time",
        "   summary regeneration if any entries changed.",
        "",
        "2. Report the final counts to the user inline:",
        "   `{added: N, updated: N, deprecated: N, noop: N}`",
        "   plus a one-line note on anything deferred for a future run.",
        "",
        "3. Call `koan_complete_step`. The curation phase ends here",
        "   and the workflow is complete.",
    ]
    return StepGuidance(title=STEP_NAMES[2], instructions=instructions)


# -- Step dispatch -------------------------------------------------------------

_STEPS = {
    1: _step_1_inventory,
    2: _step_2_memorize,
}


def step_guidance(step: int, ctx: PhaseContext) -> StepGuidance:
    fn = _STEPS.get(step)
    if fn is None:
        return StepGuidance(title=f"Step {step}", instructions=[f"Execute step {step}."])
    return fn(ctx)


# -- Lifecycle -----------------------------------------------------------------

def get_next_step(step: int, ctx: PhaseContext) -> int | None:
    if step < TOTAL_STEPS:
        return step + 1
    return None


def validate_step_completion(step: int, ctx: PhaseContext) -> str | None:
    return None


async def on_loop_back(from_step: int, to_step: int, ctx: PhaseContext) -> None:
    pass

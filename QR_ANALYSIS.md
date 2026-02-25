# QR Failure Handling & Fix Mode Analysis

## Executive Summary

This document analyzes how QR (Quality Review) failures halt execution in the koan plan-design phase and how the reference executor implements fix loops. The analysis covers three key questions:

1. **Does QR failure halt the plan-design phase?** YES -- failures trigger a deterministic gate that either spawns a fix loop or force-proceeds after max iterations.
2. **What is the plan specification for QR fix loops?** Architect is re-spawned with `--koan-fix` flag and a QR failure report appended to context.
3. **What are the executor modes?** Initial mode (first-time work) vs. fix mode (targeted repair after QR failures).

---

## Part 1: QR Failure Halts Execution (Confirmed)

### How the QR Gate Works (Reference Executor)

The reference executor in `~/.claude/skills/scripts/skills/planner/orchestrator/executor.py` implements a **9-step workflow** for execution (not planning):

```
Step 1: Execution Planning (analyze, build wave list)
Step 2: Reconciliation (validate existing code)
Step 3: Implementation (dispatch developers)
Step 4: Code QR (quality review of code)
Step 5: Code QR GATE (route pass/fail)  <-- HALTS on FAIL
Step 6: Documentation (TW pass)
Step 7: Doc QR (quality review of docs)
Step 8: Doc QR GATE (route pass/fail)   <-- HALTS on FAIL
Step 9: Retrospective
```

**Key excerpt from executor.py:**

```python
CODE_QR_GATE = GateConfig(
    qr_name="Code QR",
    work_step=3,          # If FAIL: loop back to step 3
    pass_step=6,          # If PASS: advance to step 6
    pass_message="Code quality verified. Proceed to documentation.",
    fix_target=AgentRole.DEVELOPER,  # Developer fixes issues
)

def format_gate(step: int, gate: GateConfig, qr: QRState, total_steps: int) -> str:
    """Format gate step output."""
    if qr.passed:
        next_cmd = f"python3 -m {MODULE_PATH} --step {gate.pass_step}"
    else:
        next_iteration = qr.iteration + 1
        next_cmd = f"python3 -m {MODULE_PATH} --step {gate.work_step} --qr-fail --qr-iteration {next_iteration}"
    return format_step(body, next_cmd, title=f"{gate.qr_name} Gate")
```

**Execution halts on FAIL** because:
- QR GATE step 5 checks `qr.passed` property
- If FAIL: routes back to step 3 (implementation) with `--qr-fail` flag
- Step 3 detects fix mode and spawns developer with targeted repair instructions
- No automatic proceed to step 6 (documentation)

### How the QR Gate Works (Koan Plan-Design)

The koan project applies the same pattern to the plan-design phase. Based on the plan specification (section 4.2 and 5):

```
Plan-Design Phase (Architect):
  ├─ execution: spawn architect subagent
  │    (6-step exploration + plan writing)
  │
  ├─ qr-decompose: spawn decomposer subagent
  │    (13-step QR item generation)
  │
  ├─ qr-verify: pool of reviewer subagents
  │    (parallel verification, PASS/FAIL per item)
  │
  └─ gate (deterministic code, no LLM)
       PASS -> advance to plan-code
       FAIL -> re-spawn architect with fix report (up to 5x)
                iteration escalates severity filtering
                after 5 iterations, force-proceed
```

**Plan specification (section 4.2.1 "QR Gate"):**

```typescript
function routeGate(
  phase: Phase,
  qrResult: "pass" | "fail",
  iteration: number,
): NextStep {
  if (qrResult === "pass") {
    deleteQRState(phase);
    return nextPhase(phase);
  }
  const maxIterations = 5;
  if (iteration >= maxIterations) {
    return nextPhase(phase); // Force proceed, document remaining issues
  }
  return { phase, subPhase: "execution", mode: "fix", iteration: iteration + 1 };
}
```

**Execution halts on FAIL** because:
- Gate routing is deterministic (pure code, no LLM)
- FAIL does not auto-advance
- Only PASS or max-iterations advances to next phase
- Fix mode spawns architect fresh with failure report

---

## Architecture Pattern (From Old System)

### Two-Phase Workflow Pattern

QR operates in two distinct phases per plan phase (plan-design, plan-code, plan-docs, impl-code, impl-docs):

1. **DECOMPOSITION** (QR Decompose)
   - 8-step LLM workflow generating atomic verification items
   - Creates `qr-{phase}.json` with items array
   - Each item: `{id, scope, check, status: "TODO", severity, [parent_id], [group_id]}`
   - Grouping logic (steps 9-13) organizes items by: parent-child, umbrella, component, concern, affinity

2. **VERIFICATION** (QR Verify)
   - Parallel dispatch of single items via `--qr-item` flag
   - Each subagent verifies ONE item (ANALYZE -> CONFIRM -> SUMMARY pattern)
   - Atomic mutation via `cli/qr.py` with file locking (no race conditions)
   - Output: one-word PASS/FAIL only (findings in CLI --finding flag)

### Key Files in Old System

**Decomposition Scripts:**
- `/Users/lmergen/.claude/skills/scripts/skills/planner/quality_reviewer/plan_design_qr_decompose.py`
- `plan_code_qr_decompose.py`
- `plan_docs_qr_decompose.py`
- Shared: `skills/planner/quality_reviewer/prompts/decompose.py` (8-step workflow, grouping logic)

**Verification Base:**
- `skills/planner/quality_reviewer/qr_verify_base.py` (VerifyBase class, step routing, item loading)
- Specific: `plan_design_qr_verify.py`, `plan_code_qr_verify.py`, `plan_docs_qr_verify.py`
- Shared: `skills/planner/shared/qr/utils.py` (load_qr_state, get_qr_item, format_qr_item_for_verification)

**CLI Tools:**
- `skills/planner/cli/qr.py` (update-item with file locking)
- `skills/planner/cli/qr_commands.py` (update_item function, atomic write)

## Decomposition Workflow (8 Steps)

### Step 1: Absorb Context
- Load context.json and plan.json from STATE_DIR
- Parse planning context (overview, constraints, invisible knowledge)
- Task: Summarize in 2-3 sentences what success looks like for this phase

### Step 2: Holistic Concerns (Top-Down)
- Brainstorm concerns specific to the phase (out-of-scope items explicitly excluded)
- Phase-specific examples (e.g., plan-design: "Missing decisions", "Policy defaults without backing")
- Output: Bulleted list, quantity over quality

### Step 3: Structural Enumeration (Bottom-Up)
- List plan elements that exist in plan.json
- Use IDs where available (DL-001, M-001, etc.)
- Phase-specific (e.g., plan-design: decisions, constraints, risks, milestones, code_intents)

### Step 4: Gap Analysis (Shared)
- Compare Step 2 concerns vs Step 3 elements
- Identify gaps: concerns not covered by elements, elements with no concerns
- Output: Umbrella vs specific items, cross-cutting vs targeted

### Step 5: Generate Items (Phase-Specific Severity)
- Create verification items with UMBRELLA + SPECIFIC pattern
- Assign severity (MUST/SHOULD/COULD per phase-specific rules)
- Format: `{id, scope, check, status: "TODO", severity}`

### Step 6: Atomicity Check (Shared)
- Review each item for atomicity (tests ONE thing, unambiguous pass/fail)
- Split non-atomic MUST items into parent + children (qa-002 -> qa-002a, qa-002b)
- Children inherit parent's severity, have parent_id field

### Step 7: Coverage Validation (Shared)
- Use Step 3 enumeration as checklist
- Verify each element has at least one item covering it
- Verify each concern from Step 2 has at least one item
- Add items if gaps found (prefer over-coverage)

### Step 8: Finalize
- Write qr-{phase}.json to STATE_DIR
- Format: `{phase, iteration: 1, items: [...]}`
- No fixed item count; content-driven

### Steps 9-13: Grouping (Shared)
- **Step 9:** Structural grouping (deterministic: parent-child resolution, umbrella batching)
- **Step 10:** Component grouping (items verifying different aspects of same element)
- **Step 11:** Concern grouping (items checking same quality dimension across elements)
- **Step 12:** Affinity grouping (semantic similarity for remaining items)
- **Step 13:** Final validation (naming conventions, large group review, singleton review)

## Phase-Specific Prompts

### Plan-Design Phase

**Step 1 Absorb:**
```
Read plan.json from STATE_DIR:
  cat $STATE_DIR/plan.json | jq '.'

SCOPE: Plan structure and decision quality.

Focus on:
  - planning_context.decisions (completeness, reasoning quality)
  - planning_context.constraints (all documented?)
  - planning_context.risks (identified and addressed?)
  - milestones[].code_intents (structure present?)
  - invisible_knowledge (captured?)

OUT OF SCOPE (verified in later phases):
  - Code correctness (plan-code phase)
  - Documentation quality (plan-docs phase)
```

**Step 2 Concerns:**
```
Brainstorm concerns specific to PLAN STRUCTURE:
  - Missing decisions (non-obvious choices not logged)
  - Policy defaults without user backing
  - Orphan milestones (no code_intents)
  - Invalid references (decision_refs point nowhere)
  - Reasoning chains too shallow
  - Risks identified but not addressed

DO NOT brainstorm code or documentation concerns (out of scope)
```

**Step 3 Enumeration:**
```
For plan-design, enumerate PLAN STRUCTURE ARTIFACTS:

DECISIONS:
  - Each decision in planning_context.decisions (ID, decision text)
  - Has reasoning? Multi-step chain?

CONSTRAINTS:
  - Each constraint in planning_context.constraints (ID, type)
  - User-specified or inferred?

RISKS:
  - Each risk in planning_context.risks (ID, risk text)
  - Has mitigation?

MILESTONES:
  - Each milestone (ID, name, count of code_intents)
  - Each code_intent with decision_refs (ID, which decisions referenced)

INVISIBLE KNOWLEDGE:
  - system, invariants[], tradeoffs[] content
```

**Step 5 Severity (Plan-Design):**
```
SEVERITY ASSIGNMENT (per conventions/severity.md, plan-design scope):

  MUST (blocks all iterations):
    - DIAGRAM categories:
      * ORPHAN_NODE: node with zero edges
      * INVALID_EDGE_REF: edge references missing node
      * INVALID_SCOPE_REF: scope references non-existent milestone
    - KNOWLEDGE subset:
      * DECISION_LOG_MISSING: non-trivial choice without logged rationale
      * POLICY_UNJUSTIFIED: policy default without Tier 1 backing
      * ASSUMPTION_UNVALIDATED: architectural assumption without citation

  SHOULD (iterations 1-4):
    - Shallow reasoning chains (premise without implication)
    - Missing risk mitigations
    - Incomplete constraint documentation

  COULD (iterations 1-3):
    - Cosmetic plan formatting
    - Minor inconsistencies in naming
```

**Component Examples:**
```
  - A milestone
  - A major decision
  - A constraint category
```

**Concern Examples:**
```
  - Reasoning chain quality
  - Reference integrity
  - Risk coverage
```

### Plan-Code Phase

**Step 1 Absorb:**
```
Read plan.json from STATE_DIR:
  cat $STATE_DIR/plan.json | jq '.'

SCOPE: Code correctness in planned changes.

Focus on:
  - milestones[].code_intents[] -- what changes are intended
  - milestones[].code_changes[] -- actual diff content
  - code_changes[].diff (context lines must match codebase)
  - code_changes[].why_comments[].decision_ref (refs must exist)

OUT OF SCOPE (already verified in plan-docs phase):
  - Documentation quality (temporal contamination, WHY-not-WHAT)
  - README/CLAUDE.md content
  - Invisible knowledge coverage
```

**Step 2 Concerns:**
```
Brainstorm concerns specific to CODE CORRECTNESS:
  - Context lines don't match actual codebase
  - Diff format violations (missing +/- prefixes, wrong line counts)
  - Code_intents without corresponding code_changes
  - Invalid decision_refs in why_comments
  - Type errors, missing imports, API mismatches
  - Convention violations (per project style)

DO NOT brainstorm documentation concerns (out of scope for this phase).
```

**Step 3 Enumeration:**
```
For plan-code, enumerate CODE CHANGE ARTIFACTS:

INTENTS:
  - Each milestone's code_intents (ID, description)
  - Intent-to-change mapping (which intents have changes?)

CHANGES:
  - Each code_change (ID, file path, line range)
  - Files touched across all changes
  - Context line locations requiring verification

REFERENCES:
  - decision_refs in why_comments (do they exist in planning_context?)

DO NOT enumerate:
  - documentation{} fields (plan-docs's job)
  - readme_entries (plan-docs's job)
```

**Step 5 Severity (Plan-Code):**
```
SEVERITY ASSIGNMENT (per conventions/severity.md, plan-code scope):

  MUST (blocks all iterations):
    - ASSUMPTION_UNVALIDATED: architectural assumption without citation
    - MARKER_INVALID: intent marker without valid explanation
    - decision_ref references non-existent decision

  SHOULD (iterations 1-4) - STRUCTURE categories:
    - GOD_OBJECT: >15 methods OR >10 deps
    - GOD_FUNCTION: >50 lines OR >3 nesting
    - CONVENTION_VIOLATION: violates documented project convention
    - TESTING_STRATEGY_VIOLATION: tests don't follow confirmed strategy

  COULD (iterations 1-3) - COSMETIC:
    - TOOLCHAIN_CATCHABLE: errors the compiler/linter would flag
    - FORMATTER_FIXABLE: style issues fixable by formatter
    - DEAD_CODE: unused functions, impossible branches

DO NOT use KNOWLEDGE categories for documentation issues --
those are plan-docs's responsibility.
```

**Component Examples:**
```
  - A file being modified
  - A module/package
  - A code_intent cluster
```

**Concern Examples:**
```
  - Error handling consistency
  - Type safety across boundaries
  - Testing boundary clarity
```

### Plan-Docs Phase

**Step 1 Absorb:**
Similar structure, focus on doc_diff fields in code_changes

**Step 2 Concerns:**
- Temporal contamination in doc_diffs (change-relative language)
- Baseline references (documentation assumes prior state)
- doc_diffs missing for non-empty diffs
- decision_refs in doc_diffs not captured

**Step 3 Enumeration:**
- doc_diff content per code_change
- documentation{} fields (function docstrings, module comments)
- readme_entries content
- decision_log coverage in documentation

**Step 5 Severity (Plan-Docs):**
Only KNOWLEDGE categories (TW cannot fix code):
- TEMPORAL_CONTAMINATION
- BASELINE_REFERENCE (doc assumes prior state)
- MISSING_DOC_DIFF (diff present, doc_diff absent)
- DECISION_UNCOVERED (decision not referenced in any doc_diff)

## Verification Workflow (Per-Item Parallelization)

### Base Class: VerifyBase

Handles:
1. Step type routing (CONTEXT, ANALYZE, CONFIRM, SUMMARY)
2. Item loading from qr-{phase}.json
3. Dynamic step formula: `total_steps = 1 + (2 * num_items) + 1`
   - Step 1: CONTEXT (load shared state)
   - Steps 2..2N+1: ANALYZE/CONFIRM pairs per item
   - Final step: SUMMARY

### CONTEXT Step
- Load conventions, phase rules, context.json, plan.json
- List all items to verify
- Display severity and scope for each

### ANALYZE Step (Per Item)
- Explore codebase if needed
- Form preliminary conclusion (PASS or FAIL)
- Task output: narrative analysis (no tool call yet)

### CONFIRM Step (Per Item)
- Verify confidence in preliminary conclusion
- Execute CLI command to record result:
  ```bash
  python3 -m skills.planner.cli.qr --state-dir {state_dir} --qr-phase {phase} \
    update-item {item_id} --status PASS
  ```
  Or:
  ```bash
  python3 -m skills.planner.cli.qr --state-dir {state_dir} --qr-phase {phase} \
    update-item {item_id} --status FAIL --finding '<explanation>'
  ```
- Tool call blocks until file lock released (atomic update)

### SUMMARY Step
- Count results, output single word: PASS or FAIL
- EXACT FORMAT REQUIRED:
  - Output EXACTLY ONE WORD: "PASS" or "FAIL"
  - No markdown headers (##, **)
  - No "VERDICT:" prefix
  - No explanation, prose, or reasoning
  - Findings go in --finding flag, NOT in output

## Phase-Specific Verification Guidance

### Plan-Design Verification

**Macro Check (scope: "\*"):**
```
MACRO CHECK - Verify across entire plan.json:

  Read plan.json:
    cat {state_dir}/plan.json | jq '.'
```

**Milestone Check (scope: "milestone:M-001"):**
```
MILESTONE CHECK - Focus on M-001:

  Read milestone:
    cat {state_dir}/plan.json | jq '.milestones[] | select(.id == "M-001")'
```

**Code Intent Check (scope: "code_intent:CI-M-001-001"):**
```
CODE INTENT CHECK - Focus on CI-M-001-001:

  Read intent (find containing milestone first):
    cat {state_dir}/plan.json | jq '.milestones[].code_intents[] | select(.id == "CI-M-001-001")'
```

**Check-Specific Guidance:**

Decision Log Verification:
```
DECISION LOG VERIFICATION:
  - Each entry should have multi-step reasoning
  - BAD: 'Polling | Webhooks unreliable'
  - GOOD: 'Polling | 30% webhook failure -> need fallback anyway'
```

Policy Default Verification:
```
POLICY DEFAULT VERIFICATION:
  - Policy defaults affect user/org (lifecycle, capacity, failure handling)
  - Must have Tier 1 (user-specified) backing in decision_log
  - Technical defaults can use Tier 2-3 backing
```

Code Intent Verification:
```
CODE INTENT VERIFICATION:
  - Each implementation milestone needs code_intents
  - Each code_intent needs file path and behavior
  - decision_refs should point to valid decision_log entries
```

### Plan-Code Verification

Similar structure with code-specific checks:
- Context line verification (diff patterns exist in actual files)
- Diff format validation (RULE 0/1/2)
- Intent linkage (code_change.intent_ref valid)
- Decision ref validity
- Temporal contamination in comments
- WHY-not-WHAT quality

### Plan-Docs Verification

Doc-specific checks:
- Temporal contamination in doc_diffs
- Baseline references (doc assumes prior state)
- Code without docs (diff present, doc_diff absent)
- Invalid diff format
- Decision coverage in docs
- WHY-not-WHAT verification
- Missing docstrings

## Data Structures

### QR Item (qr-{phase}.json)

```typescript
interface QRItem {
  id: string;                    // e.g., "plan-001", "qa-002a"
  scope: string;                 // "*" (macro) or "element:ID" or "file:path"
  check: string;                 // Description of what to verify
  status: "TODO" | "PASS" | "FAIL";
  severity?: "MUST" | "SHOULD" | "COULD";  // Default: "SHOULD"
  finding?: string;              // Only for FAIL status
  parent_id?: string;            // For split items (qa-002a has parent_id: "qa-002")
  group_id?: string;             // For grouping (umbrella, component-*, concern-*, affinity-*, parent-*)
  version?: number;              // Default: 1, incremented on each update
}

interface QRState {
  phase: string;                 // "plan-design", "plan-code", etc.
  iteration: number;             // Current iteration (1 on first decompose)
  items: QRItem[];
}
```

### Severity Blocking Rules

Per iteration:
- Iteration 1: MUST blocks all 4 iterations of fixes, SHOULD blocks iterations 1-4, COULD blocks 1-3
- Iteration 2: MUST blocks iterations 2-5, SHOULD blocks 2-5, COULD blocks 2-4
- Iteration 3: MUST blocks iterations 3-6, SHOULD blocks 3-6, COULD blocks 3-5
- Iteration 4: MUST blocks iterations 4+, SHOULD blocks 4+, COULD blocks 4+
- After iteration 4: No blocking (move to manual review)

## Integration with Koan Architecture

### Expected File Structure
```
src/planner/phases/
  qr/
    decompose/
      phase.ts          # QRDecomposePhase class (8-step workflow)
      prompts.ts        # Phase-specific step prompts
    verify/
      phase.ts          # QRVerifyPhase class (item-based verification)
      prompts.ts        # Verification guidance per phase
    lib/
      items.ts          # QRItem type, load/save, atomic mutations
      grouping.ts       # Steps 9-13 grouping logic
```

### Phase Registration
```typescript
// In phases/dispatch.ts
if (config.role === "quality-reviewer" && config.phase === "plan-design") {
  const phase = new QRDecomposePhase(...);
  await phase.begin();
}
```

### Tool Registration
- QR tools likely smaller subset than plan-design (mainly read tools, no plan mutations)
- Tools may include: qr_update_item (atomic write), qr_load_state (read), qr_get_item (lookup)

## Critical Implementation Notes

### 1. Decomposition is Single-Run
- Decompose runs ONCE per phase (steps 1-8, 9-13)
- Orchestrator skips decompose if qr-{phase}.json already exists with iteration >=1
- Each phase has own decomposition script (can't share due to phase-specific prompts)

### 2. Verification is Parallel
- Each item dispatched as separate subagent with --qr-item flag
- File locking in CLI prevents race conditions
- No shared state mutation; each agent writes its own result atomically

### 3. Step Gates Must Use Blocklists
- Whitelist fails open (blocks read tools unintentionally)
- Blocklist defers to checkPermission for everything not explicitly gated
- Example: `if (step < 6 && PLAN_MUTATION_TOOLS.has(name)) { block }`

### 4. Findings in CLI Flag, Not Output
- Tool result is NOT return value; findings go in `--finding` flag
- SUMMARY step outputs ONE WORD only (PASS or FAIL)
- This avoids "text + tool_call in same response" bug (GPT-5-codex)

### 5. invoke_after Two-Part Gate
- Every step prompt ends with "WHEN DONE: call koan_complete_step"
- Tool description includes "Do NOT call until told"
- Dual gates ensure single transition per step

### 6. Disk-Backed Mutations
- Every tool mutation writes qr-{phase}.json immediately
- No finalize pattern; descriptive feedback on each write
- This prevents LLM from skipping intermediate mutations

### 7. Severity Blocking vs Iteration Count
- Blocking set determined at gate time, not item creation time
- by_blocking_severity(iteration) is a predicate factory
- Iteration 0 not used; iteration 1 is first decompose, iteration 2+ are retries

## Migration Checklist

- [ ] Create QRDecomposePhase class with 8-step + 5-step grouping workflow
- [ ] Implement phase-specific prompts for plan-design, plan-code, plan-docs
- [ ] Create QRVerifyPhase class with CONTEXT/ANALYZE/CONFIRM/SUMMARY routing
- [ ] Implement VerifyBase-like step mapping (total_steps formula, item routing)
- [ ] Implement atomic QRItem mutations with file locking
- [ ] Add qr_update_item tool (wrapper around file-locked write)
- [ ] Add qr_load_state, qr_get_item tools (read-only)
- [ ] Register phases in dispatch.ts for quality-reviewer role
- [ ] Add QR phase detection to before_agent_start handler
- [ ] Implement SUMMARY step output validation (one word only)
- [ ] Test decompose single-run enforcement (skip if iteration >=1)
- [ ] Test parallel verify with file locking (concurrent writes)
- [ ] Test severity blocking at iteration thresholds
- [ ] Copy exact prompts from Python scripts (no rewriting)

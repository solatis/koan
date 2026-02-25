# QR Failure Handling & Fix Mode Analysis

## Executive Summary

This document analyzes how QR (Quality Review) failures halt execution in the koan plan-design phase and how the reference executor implements fix loops. The analysis covers three key questions:

1. **Does QR failure halt the plan-design phase?** YES -- failures trigger a deterministic gate that either spawns a fix loop or force-proceeds after max iterations.
2. **What is the plan specification for QR fix loops?** Architect is re-spawned with `--koan-fix` flag and a QR failure report appended to context.
3. **What are the executor modes?** Initial mode (first-time work) vs. fix mode (targeted repair after QR failures).

---

## Part 1: QR Failure Halts Execution (Confirmed)

### How the QR Gate Works (Reference Executor)

The reference executor in `~/.claude/skills/scripts/skills/planner/orchestrator/executor.py` implements a **9-step workflow** for execution:

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

The koan project applies the same pattern. Based on the plan specification (section 4.2 and 5 of plans/2026-02-10-init.md):

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

**Plan specification routing logic (section 4.2.1):**

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
- Gate routing is deterministic (pure code, not prompt-based)
- FAIL does not auto-advance
- Only PASS or max-iterations advances to next phase
- Fix mode spawns architect fresh with failure report

---

## Part 2: Plan Specification for QR Fix Loops

### Fix Mode Activation

From plan section 4.2 "First attempt vs. fix mode":

> When a phase's QR gate returns FAIL, the orchestrator re-spawns the subagent with an additional flag (`--koan-fix`) and appends the QR failure report to the context file. The subagent's role hooks detect fix mode and adjust step instructions to focus on fixing specific issues identified by the QR.

**Mechanism:**

1. **Gate detects FAIL** → compute `iteration + 1`
2. **Orchestrator spawns subagent** with:
   - `--koan-fix` flag (new)
   - `--koan-fix-iteration N` flag (new)
   - Same `--koan-plan-dir` (plan.json + context.json + qr-plan-design.json all present)
3. **Context file is mutated** to append QR failures:
   - Original 8 context categories remain (read-only)
   - QR failures appended in a new `qr_failures` section
4. **Role hooks detect fix mode** via flags in `before_agent_start`
5. **Step instructions adjust** to focus on fixing

### Reference Architect Fix Prompt

The reference architect fix script is `~/.claude/skills/scripts/skills/planner/architect/plan_design_qr_fix.py` (3-step workflow):

**Step 1: Load QR Failures**

```
FIX MODE - QR Iteration {qr_iteration}

QR-COMPLETENESS found issues in the plan.

FAILED QR ITEMS TO FIX (address these FIRST):
================================================
[plan-001] Decision log completeness
    Scope: decision_log entry DL-005
    Finding: Decision reference missing backing premise

[plan-002] Code intent specification
    Scope: code_intent id CI-M-001-001
    Finding: Behavior description incomplete (unclear acceptance criteria)

================================================

PLANNING CONTEXT (reference for semantic validation):
(context.json displayed for validation reference)

For EACH failed item:
  1. Read the 'finding' field to understand the issue
  2. Identify what in plan.json needs to change
  3. Note the fix approach for step 2
```

**Step 2: Apply Targeted Fixes**

```
APPLY targeted fixes to plan.json using CLI commands.

Missing decision_log entry:
  python3 -m skills.planner.cli.plan --state-dir $STATE_DIR set-decision \
    --decision '<what was decided>' \
    --reasoning '<premise -> implication -> conclusion>'

BATCH MODE (preferred):
  python3 -m skills.planner.cli.plan --state-dir $STATE_DIR batch '[
    {"method": "set-decision", "params": {...}, "id": 1},
    {"method": "set-intent", "params": {...}, "id": 2}
  ]'

CONSTRAINT: Fix ONLY the failing items. Don't refactor passing items.
```

**Step 3: Validate Fixes**

```
Run structural validation:
  python3 -m skills.planner.cli.plan validate --phase plan-design

SELF-CHECK each fixed item:
  For each FAIL item you addressed:
    - Does the fix address the specific finding?
    - Does the fix introduce new issues?

If validation passes:
  Your complete response must be exactly: PASS
  Do not add summaries, explanations, or any other text.
```

### Key Design Points in Fix Mode

1. **QR failures explicitly listed** -- The architect sees exactly which items failed + why (the "finding" field)
2. **Plan mutations via existing CLI** -- Fix mode doesn't add new mutation tools, just focuses the prompt on specific items
3. **Targeted not holistic** -- Fix mode does NOT re-explore codebase. It reads the QR report and applies surgical fixes.
4. **No flailing** -- The constraint "Fix ONLY the failing items" prevents second-guessing the entire plan
5. **Validation is mandatory** -- Each fix iteration must pass `python3 -m ... validate` before reporting PASS

### Iteration Escalation with Severity Filtering

QR items have a `severity` field: MUST | SHOULD | COULD

**Severity filtering logic (implied by shared/qr/constants.py):**

```python
def get_blocking_severities(iteration: int) -> Set[str]:
    """Items that block at this iteration.

    iteration 1: MUST only
    iteration 2: MUST, SHOULD
    iteration 3+: MUST, SHOULD, COULD (all)
    """
```

**Meaning:** On iteration 1, only critical (MUST) items block. By iteration 3, even minor (COULD) items block. This escalates pressure to fix progressively more issues.

---

## Part 3: Executor Modes (Initial vs. Fix)

### Reference Executor: Initial Mode

When a phase is first executed (no prior failures):

**Step 3: Implementation (Initial Mode)**

```python
def format_step_3_implementation(qr: QRState, total_steps: int, ...) -> str:
    if qr.state == LoopState.RETRY:
        # Fix mode (handled separately)
        ...
    else:
        # Initial mode
        actions.extend([
            "Execute ALL milestones using wave-aware parallel dispatch.",
            "",
            "WAVE-AWARE EXECUTION:",
            "  - Milestones within same wave: dispatch in PARALLEL",
            "  - Waves execute SEQUENTIALLY",
            "",
            "FOR EACH WAVE:",
            "  1. Dispatch developer agents for ALL milestones in wave",
            "  2. Each prompt includes: plan, milestone, files, acceptance criteria",
            "  3. Wait for ALL agents in wave to complete",
            "  4. Run tests: pytest / tsc / go test -race",
            "  5. Proceed to next wave",
            "",
            "After ALL waves complete, proceed to Code QR.",
        ])
```

**Initial mode** is the "full breadth" mode:
- No prior failures to fix
- Execute all milestones
- Waves in sequence, milestones within wave in parallel
- Standard tests + validation

### Reference Executor: Fix Mode

When a QR gate returns FAIL and iteration < 5:

**Step 3: Implementation (Fix Mode)**

```python
def format_step_3_implementation(qr: QRState, total_steps: int, ...) -> str:
    if qr.state == LoopState.RETRY:
        actions.append(format_state_banner("IMPLEMENTATION FIX", qr.iteration, "fix"))
        actions.append("FIX MODE: Code QR found issues.")
        actions.append("")

        mode_script = get_mode_script_path("dev/fix-code.py")
        invoke_cmd = f"python3 -m {mode_script} --step 1 --qr-fail --qr-iteration {qr.iteration}"

        actions.append(subagent_dispatch(
            agent_type="developer",
            command=invoke_cmd,
        ))
        actions.append("Developer reads QR report and fixes issues in <milestone> blocks.")
        actions.append("After developer completes, re-run Code QR for fresh verification.")
```

**Fix mode** is the "targeted repair" mode:
- QR failures are present (in memory and on disk)
- Dispatch specialized fix agent (different script/prompts)
- Agent reads QR failure items
- Agent applies fixes to milestones mentioned in failures
- Re-run QR immediately after (fresh verification)

### Comparison Table

| Aspect | Initial Mode | Fix Mode |
|--------|--------------|----------|
| **Trigger** | First execution | QR FAIL (iteration < 5) |
| **Context** | No prior failures | QR items with status=FAIL + findings |
| **Scope** | All milestones | Only milestones in QR failures |
| **Agent Dispatch** | Full work agent | Specialized fix agent |
| **Step Sequence** | Role's standard N-step | 3-step fix workflow |
| **Tools Available** | Full read + write | Same tools (focus via prompt) |
| **Exit Condition** | Role completes final step | PASS to QR (no FAIL) |
| **Next** | Proceed to QR decompose | Re-run QR immediately |
| **Iteration** | N/A | 1, 2, 3, ... (max 5) |

### How the Executor Decides Which Mode

**Flag detection in executor.py:**

```python
# format_step_3_implementation
state = LoopState.RETRY if qr_fail else LoopState.INITIAL

# Gate's FAIL routing:
next_cmd = f"python3 -m {MODULE_PATH} --step {work_step} --qr-fail --qr-iteration {next_iteration}"
```

When gate returns FAIL, step 3 is re-invoked with `--qr-fail --qr-iteration 2`, and the formatter detects fix mode.

---

## Part 4: Reference Implementation Deep Dive

### Shared QR Infrastructure

Located in `~/.claude/skills/scripts/skills/planner/shared/qr/`:

**types.py:**

```python
class QRStatus(Enum):
    PASS = "pass"
    FAIL = "fail"

class LoopState(Enum):
    INITIAL = "initial"
    RETRY = "retry"
    COMPLETE = "complete"

@dataclass
class QRState:
    iteration: int = 1
    state: LoopState = LoopState.INITIAL
    status: QRStatus | None = None

    @property
    def passed(self) -> bool:
        return self.status == QRStatus.PASS

    def transition(self, status: QRStatus) -> None:
        if status == QRStatus.PASS:
            self.state = LoopState.COMPLETE
        else:
            self.state = LoopState.RETRY
            self.iteration += 1

@dataclass
class GateConfig:
    qr_name: str
    work_step: int           # Where to loop back on FAIL
    pass_step: int | None    # Where to go on PASS
    pass_message: str
    fix_target: AgentRole | None  # Developer / Writer / Architect
```

**gates.py:**

```python
def build_gate_output(
    module_path: str,
    qr_name: str,
    qr: QRState,
    work_step: int,
    pass_step: int | None,
    pass_message: str,
    fix_target: AgentRole | None,
    state_dir: str,
) -> GateResult:
    """Build complete gate step output for QR gates.

    Gates route to either:
    - pass_step: QR passed, proceed to next workflow phase
    - work_step: QR failed, loop back to fix issues
    """
    if qr.passed:
        next_cmd = f"python3 -m {module_path} --step {pass_step}"
    else:
        next_cmd = f"python3 -m {module_path} --step {work_step} --state-dir {state_dir}"

    return GateResult(
        output=format_step(body, next_cmd, title=title),
        terminal_pass=qr.passed and pass_step is None,
    )
```

### How the Architect Fix Prompts Load QR Failures

**plan_design_qr_fix.py, step 1:**

```python
def get_step_guidance(step: int, module_path: str = None, **kwargs) -> dict:
    if step == 1:
        state_dir = kwargs.get("state_dir", "")
        qr_iteration = get_qr_iteration(state_dir, PHASE)

        # Load failed items from qr-{phase}.json
        qr_state = load_qr_state(state_dir, PHASE)
        failed_items_block = format_failed_items_for_fix(qr_state)

        return {
            "title": STEPS[1],
            "actions": [
                f"FIX MODE - QR Iteration {qr_iteration}",
                "",
                "QR-COMPLETENESS found issues in the plan.",
                "",
                failed_items_block,  # <- Explicit list of failures
                "",
                "For EACH failed item:",
                "  1. Read the 'finding' field to understand the issue",
                "  2. Identify what in plan.json needs to change",
                "  3. Note the fix approach for step 2",
            ],
        }
```

**format_failed_items_for_fix output example:**

```
============================================================
FAILED QR ITEMS TO FIX (address these FIRST):
============================================================

[QR-plan-design-001] Decision completeness
    Scope: decision_log entry (id: DL-003)
    Finding: Caching strategy selected but no justification.

[QR-plan-design-002] Intent specification
    Scope: code_intent (id: CI-M-001-001)
    Finding: Behavior unclear: "Add caching layer" -- where? What TTL?

[QR-plan-design-003] Risk documentation
    Scope: known_risks
    Finding: Redis failure mode not documented.

============================================================
```

---

## Part 5: Koan's QR Specification

### Section 4.2: QR Block Pattern

**Plan-Design Phase Structure:**

```
Phase 2: PLAN-DESIGN
├─ Execution (architect explores + writes plan)
├─ QR Decompose (decomposer generates items)
├─ QR Verify (reviewers verify items)
└─ Gate (route PASS->phase3 or FAIL->reexecute_with_fix)
```

### Section 4.2.1: QR Decomposition (13-step Workflow)

The decomposer produces items with:
- `id`: unique item ID
- `scope`: `*` (cross-cutting) or element reference
- `check`: the verification question
- `status`: TODO | PASS | FAIL
- `finding`: explanation of FAIL (populated by reviewers)
- `severity`: MUST | SHOULD | COULD

### Section 4.2.2: QR Verification (Parallel Subagents)

Each reviewer subagent:
1. Receives assigned item group
2. For each item: ANALYZE -> CONFIRM -> update state
3. Returns per-item status
4. Aggregate: ANY FAIL = phase FAIL

### Section 4.2.3: Fix Mode (Key Design Decision)

From section 4.2:

> When a phase's QR gate returns FAIL, the orchestrator re-spawns the subagent with an additional flag (`--koan-fix`) and appends the QR failure report to the context file. The subagent's role hooks detect fix mode and adjust step instructions to focus on fixing specific issues identified by the QR.

---

## Part 6: Koan Implementation

### Key Difference: Single Phase Handler vs. Separate Scripts

**Reference executor:**
- `architect/plan_design_execute.py` (6 steps, first-time)
- `architect/plan_design_qr_fix.py` (3 steps, targeted repair)
- Separate scripts for each mode

**Koan design:**
- Single `PlanDesignPhase` handler
- Phase hooks detect `--koan-fix` flag
- Step prompts adjust at runtime in the `context` event handler
- Same tools, same workflow -- just different prompt text

### Koan Implementation Pattern (Inferred)

```typescript
// src/planner/phases/plan-design/phase.ts

export class PlanDesignPhase {
  private state: PlanDesignState & {
    fixMode: boolean;
    fixIteration: number;
  };

  async begin(): Promise<void> {
    // Detect fix mode from flags
    this.state.fixMode = this.pi.getFlag("koan-fix") === "true";
    this.state.fixIteration = parseInt(this.pi.getFlag("koan-fix-iteration") || "0");

    // Load context.json (with QR failures appended if fixMode)
    const contextPath = path.join(this.planDir, "context.json");
    const raw = await fs.readFile(contextPath, "utf8");
    this.state.contextData = JSON.parse(raw) as ContextData;
    // context.qr_failures populated by orchestrator if fixMode
  }

  private registerHandlers(): void {
    this.pi.on("context", (event) => {
      if (this.state.step !== 1) return undefined;

      let prompt = this.state.step1Prompt;

      // Adjust for fix mode
      if (this.state.fixMode) {
        prompt = adjustPromptForFixMode(
          prompt,
          this.state.fixIteration,
          this.state.contextData.qr_failures,
        );
      }

      const messages = event.messages.map((m) =>
        m.role === "user" ? { ...m, content: prompt } : m,
      );
      return { messages };
    });
  }
}

function adjustPromptForFixMode(
  basePrompt: string,
  iteration: number,
  failures: Array<{id: string; scope: string; finding: string}>,
): string {
  // Replace exploration sections with fix guidance
  // Prepend: list of failed items + findings
  // Add constraint: "Fix ONLY these items"
  // Add validation guidance
}
```

### Orchestrator-Side: Appending QR Failures to Context

When gate returns FAIL:

```typescript
// 1. Load qr-plan-design.json
const qrPath = path.join(planDir, "qr-plan-design.json");
const qr = JSON.parse(await fs.readFile(qrPath, "utf8"));

// 2. Filter FAIL items
const failures = qr.items.filter(item => item.status === "FAIL").map(item => ({
  id: item.id,
  scope: item.scope,
  finding: item.finding,
}));

// 3. Load context.json
const contextPath = path.join(planDir, "context.json");
const context = JSON.parse(await fs.readFile(contextPath, "utf8"));

// 4. Append failures
context.qr_failures = failures;
context.qr_iteration = iteration;

// 5. Write back (atomic)
await writeContext(planDir, context);

// 6. Spawn architect in fix mode
spawn("pi", [
  "-p",
  "-e", extensionPath,
  "--koan-role", "architect",
  "--koan-phase", "plan-design",
  "--koan-plan-dir", planDir,
  "--koan-fix", "true",
  "--koan-fix-iteration", String(iteration),
  "Fix the plan issues identified in the QR report.",
]);
```

---

## Summary Table: Initial vs. Fix Mode

| Dimension | Initial Mode | Fix Mode |
|-----------|--------------|----------|
| **QR State** | None (first execution) | FAIL (previous iteration) |
| **Orchestrator Decision** | Execute (fresh start) | Fix (failures present) |
| **Flags** | None | `--koan-fix true --koan-fix-iteration N` |
| **Context File** | 8 categories only | ^^ + `qr_failures` array |
| **Step Sequence** | 1=analysis, 2=exploration, ..., 6=write | 1=load failures, 2=fix, 3=validate |
| **Scope** | All codebase areas relevant to task | Only areas in QR failures |
| **Tools** | Full set (read + write) | Same set (focus via prompt) |
| **Exit** | PASS to orchestrator -> QR decompose | PASS to orchestrator -> re-run QR |
| **Iteration** | Not applicable | 1, 2, 3, ... (max 5) |
| **Severity Filter** | N/A | Escalates per iteration |
| **Outcome** | plan.json artifact | Updated plan.json (surgical fixes) |

---

## Conclusion

**QR failures halt execution in koan's plan-design phase** because the QR gate is deterministic code. The gate examines the QR result and either:
1. PASS → advance to next phase
2. FAIL + iteration < 5 → spawn architect in fix mode with failure report
3. FAIL + iteration >= 5 → force-proceed to next phase

**Fix mode is a targeted repair workflow** that differs from initial mode by:
- Running a 3-step workflow (load -> fix -> validate) instead of N-step exploration
- Reading QR failures from context + disk
- Focusing fixes on listed items only
- Escalating severity requirements each iteration

**The reference executor provides the exact implementation patterns** that koan follows, with the improvement that koan consolidates execute/fix logic into one phase handler via prompt adjustment, rather than separate scripts.


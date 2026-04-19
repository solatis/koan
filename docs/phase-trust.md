# Phase Trust Model

Design decision document for how phases in the plan workflow relate to each
other's outputs.

## Principle

Phases trust each other's outputs. Verification happens _within_ a phase,
not across phases. The user reviews artifacts at phase boundaries.

The single exception is **plan-review**, whose entire purpose is adversarial
verification of claims made by prior phases.

## Why

Re-verification across phases is the "intrinsic self-correction" anti-pattern:
the same LLM re-checking its own prior work without external feedback. Research
shows this typically degrades performance -- the model is more likely to change
correct conclusions to incorrect ones than the reverse.

The fix is structural: designate one phase (plan-review) as the verification
phase, give it an adversarial posture, and have it use the codebase as an
external verification tool (the CRITIC pattern). All other phases trust the
chain.

## Phase responsibilities

### intake (2 steps: Gather, Deepen)

- Explores the codebase, asks the user targeted questions, resolves ambiguity.
- Owns: uncertainty resolution. Its output is verified understanding.
- Downstream phases trust intake's findings as their starting point.

### plan-spec (2 steps: Analyze, Write)

- Reads codebase files to write precise implementation instructions.
- Trusts intake's findings. Reads code to understand structure for planning,
  not to re-verify what intake discovered.
- Owns: plan.md -- the implementation artifact.

### plan-review (2 steps: Read, Evaluate)

- The designated adversarial verifier. Trusts nobody.
- Opens every file the plan references and checks every claim (paths, function
  names, signatures, types) against reality.
- Owns: verification. Uses the codebase as an external tool to validate claims.
- Advisory only -- reports findings, does not modify plan.md.

### execute (2 steps: Compose, Request)

- Composes the executor handoff from plan.md and plan-review findings.
- Trusts the plan (it has been reviewed). Does not re-evaluate.
- Owns: clean handoff to the executor agent.

## Data flow

```
task_description
    |
    v
 intake  ---- questions/answers ----> user
    |
    | (trusted context in LLM memory)
    v
 plan-spec ----> plan.md
    |
    | (artifact in run_dir)
    v
 plan-review ----> severity-classified findings (in chat)
    |               \
    |                +---> loop back to plan-spec if critical/major
    v
 execute ----> koan_request_executor(artifacts, instructions)
```

## What this means for prompt design

- **Do NOT** add "verify against the actual code" directives to phases other
  than plan-review. That directive belongs exclusively to the adversarial phase.
- **Do** tell phases to trust prior phase output: "Intake has already explored
  the codebase and resolved ambiguities. Trust those findings."
- **Do** tell plan-review it trusts nobody: "You are the only phase that
  independently checks claims against reality."

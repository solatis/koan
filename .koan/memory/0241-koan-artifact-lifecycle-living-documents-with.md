---
title: 'koan artifact lifecycle: living documents with temporal-only immutability;
  the event log is the record, no freeze'
type: decision
created: '2026-06-22T22:49:44Z'
modified: '2026-06-22T22:49:44Z'
---

koan's artifact lifecycle (`koan/tools/artifact_registry.py`, `koan/projections.py`, `koan/tools/koan_tools.py`) was reworked so artifacts are living working surfaces rather than immutable-after-handoff. Leon decided this on 2026-06-22, dogfooded (koan develops koan): there is no freeze gate; plans and `milestones.md` are edited in place for their whole life; review threads and execution history accrete inside the document by convention (`## Review` and `## Execution N` sections); the only immutable record is the driver-owned append-only event log (`events.jsonl` / projections), which the LLM cannot touch. The `frozen` field on `ArtifactInfo` and its write/edit validators were removed; `brief.md` remains the one write-once artifact, and `core-flows.md`/`tech-plan.md` remain stable-after-their-producing-phase by convention. Rationale: freeze guarded a race the architecture already prevents (the executor spawn is blocking and the orchestrator is the sole writer of the plan, so it cannot mutate a plan mid-execution regardless), and the markdown was never the system of record. Alternatives rejected: keep freeze as a soft advisory marker (a marker that gates nothing is dead weight); enforce append-only on completed markdown (contradicts the stop-hard-gating goal; the event log already guarantees history). The triggering incident was a crash from the `.review.md` sidecar name colliding with the artifact-name grammar, but the change removed the whole immutability subsystem rather than patching the grammar.

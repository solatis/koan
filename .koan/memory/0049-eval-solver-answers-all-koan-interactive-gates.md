---
title: Eval runner uses yolo-mode auto-responses and post-hoc projection harvest for
  per-phase scoring
type: decision
created: '2026-04-17T12:06:18Z'
modified: '2026-06-20T03:59:12Z'
---

koan's eval runner (`evals/runner.py`) measures workflow runs without a human in the loop by combining yolo-mode auto-responses with a post-run projection harvest. It spawns koan as a subprocess with `--yolo` and `--directed-phases`; in yolo mode koan's own auto-response paths (`_yolo_yield_response` and `_yolo_ask_answer` in `koan/agents/loop.py`) resolve every phase-boundary hand-back and `koan_ask_question` with the recommended suggestion or option (falling back to a best-judgement default), so the runner needs no per-interaction involvement. The runner polls run-state until `completion` is non-null, then fetches a harvest dict from the in-process `/api/eval-harvest` endpoint, which runs `harvest_run()` against the live `ProjectionStore.events`, bucketing per-phase tool-call and artifact events against `phase_started` boundaries for downstream per-phase scoring. The harvest must run inside koan's own process because `ProjectionStore.events` is memory-only and never persisted to disk -- it cannot be reconstructed from the SSE wire format, which lacks phase attribution for artifacts.

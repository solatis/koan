---
title: New projection model duplicated cumulative token fields already tracked on
  Conversation
type: lesson
created: '2026-07-04T08:27:53Z'
modified: '2026-07-04T08:27:53Z'
---

koan projection system (`koan/projections.py`) — during implementation of per-agent token telemetry, the initial `Telemetry` Pydantic model carried `input_tokens`, `output_tokens`, `cache_read_tokens`, and `cache_write_tokens` as its own fields. These same four cumulative fields already existed on the `Conversation` model, which the projection fold updates from agent-usage events. The duplication would have created two independent tracking systems for the same data, updated by the same fold function, with no guarantee they would stay in sync — a silent divergence risk visible in the frontend usage gauges.

Root cause: when adding a new Pydantic model to the projection, the plan producer did not inventory the existing `Conversation` fields before designing the new model's schema. The producer treated `Telemetry` as a greenfield model rather than checking what `Conversation` already carried.

The mechanical plan reviewer caught the duplication. The fix removed the four cumulative fields from `Telemetry`, leaving only `context_size` (a new measurement from `Model.count_tokens()`, not tracked elsewhere) and per-turn delta fields (`delta_input_tokens`, `delta_output_tokens`, `delta_cache_read_tokens`, `delta_cache_write_tokens`). Cumulative totals remain solely on `Conversation`.

Prevention: when adding a new Pydantic model to `koan/projections.py`, read the existing models — especially `Conversation`, `Agent`, and `Run` — and verify that no field on the new model duplicates a field already tracked elsewhere in the projection. The projection fold updates multiple models from a single event; duplicate tracking across models creates divergent state with no reconciliation mechanism.

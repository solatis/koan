---
title: Read range display string derived from offset/limit fields on ToolReadEntry
  itself
type: decision
created: '2026-07-03T04:03:32Z'
modified: '2026-07-03T04:03:32Z'
---

The koan projection fold's `ToolReadEntry` type in `koan/projections.py` — the team decided that the display range for read operations (e.g., "1–80") is derived from `offset` and `limit` fields on the entry type itself, rather than computed downstream. `ToolReadEntry` carries `offset` and `limit` as stored fields; a `range` property derives the display string with an assertion that `(offset + limit) - offset == limit`. Whole-file reads (default `offset=0` with no explicit `limit`) carry no range. Rationale: the entry type is the natural home for this derivation — the fields are already present, the derivation is deterministic, and keeping it in the type avoids scattering range-formatting logic across the fold function or the frontend selector layer. Alternatives rejected: deriving the range string in the frontend selector (puts display formatting in the data-mapping layer, which should be a mechanical store-to-view-model translation); deriving it in the fold's `tool_input_delta` case (scatters type-specific logic across the fold function instead of co-locating it with the type definition). Decision surfaced during the exploration `ToolAggregateCard` redesign, where the legacy `lines` string field was unpopulated on the new code path and the range needed a reliable derivation source.

---
title: Plan grep metric format missed zero-matches edge case defined in design spec
type: lesson
created: '2026-07-04T11:29:41Z'
modified: '2026-07-04T11:29:41Z'
---

Plan authoring — a plan defined a grep metric format string `"N matches · L lines · F files"` that would produce `"0 matches · 0 lines · 0 files"` for zero-match grep results. The design spec at `docs/design-system.md` explicitly defined the zero-matches case: "Zero matches: `0 matches`, italic, `--text-muted` — not red." The plan walked the happy path (non-zero matches) but did not check the spec's edge cases. The mechanical plan reviewer caught the drift: the three-field format applied to zero matches would violate both the format string and the tone rule (zero matches must not render in failure red). Root cause: when a plan derives output formats from an external design spec, the plan author walked the spec's primary format definition but did not scan for edge-case rules (zero values, error states, boundary conditions) that override the general format. Prevention: during plan authoring, when a plan step defines output formats by referencing an external spec, walk the spec's edge cases explicitly — zero values, error states, and boundary conditions often carry their own format rules that differ from the general case. The plan reviewer should verify edge-case coverage as part of the completeness check.

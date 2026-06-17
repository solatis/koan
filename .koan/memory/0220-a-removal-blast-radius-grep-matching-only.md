---
title: A removal-blast-radius grep matching only 'lmstudio' missed the spaced 'LM
  Studio' form, leaving stale overlay doc-comments behind
type: lesson
created: '2026-06-14T10:06:03Z'
modified: '2026-06-14T10:06:03Z'
related:
- 0114-safe-deletion-patterns-for-milestone-driven.md
- 0115-plan-spec-analysis-must-inventory-non-source.md
---

While inventorying the blast radius for removing the lmstudio provider, the search matched the code identifier `lmstudio` (and `lm-studio`, `lm_studio`, `localhost:1234`, `/api/v0`) but not the human-readable spaced form "LM Studio". Two doc-comments describing the provider_models overlay as "(LM Studio + cloud)" -- in koan/state.py and koan/projections.py -- were therefore never inventoried and survived the removal as stale references (harmless, since the overlay is provider-agnostic, but misleading). Root cause: a removal inventory keyed on the code spelling of an entity omits its human-readable spelling, which appears in comments, UI strings, and docs. Prevention: when inventorying a removal blast radius for a named entity, grep every spelling variant -- the code identifier, the hyphenated and underscored forms, and the spaced/capitalized human-readable name -- before treating the inventory as complete.

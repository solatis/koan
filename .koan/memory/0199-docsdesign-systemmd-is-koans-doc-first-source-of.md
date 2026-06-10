---
title: docs/design-system.md is koan's doc-first source of truth for visual design;
  variables.css mirrors its token tables and the live components drift from it
type: context
created: '2026-06-10T22:48:57Z'
modified: '2026-06-10T22:48:57Z'
related:
- 0028-frontend-css-token-promotion-hardcode-single-use.md
- 0195-koans-frontend-profile-management-ui-was-deleted.md
---

`docs/design-system.md` is the authoritative specification for koan's frontend visual identity -- tokens, atoms, molecules, organisms, and a Design Rationale section. `frontend/src/styles/variables.css` is a mechanical translation of the doc's token tables, and the doc states the ordering rule explicitly: the doc changes first, then the CSS follows. Visual-identity changes are therefore made in the doc first and propagated to `variables.css` and components, and `variables.css` is a protected file not edited unilaterally.

The live components can run ahead of the doc, so `design-system.md` periodically drifts from the implementation and is reconciled in dedicated spec<->implementation audit passes. Such a pass on 2026-06-10 split drift into two kinds: doc-lags-code, where the implementation was correct and merge-ready doc edits caught the doc up (for example, the ProviderBadge `lmstudio` swatch is a deliberate hardcoded `#8a7e70` in `frontend/src/components/atoms/ProviderBadge.css`, not the `--status-queued` token the doc still named); and code-deviates-from-doc, where the doc is the spec and the code is fixed to match (for example, the unified `off/low/medium/high` thinking scale and the 'newest in family' model pins).

`design-system.md` is not indexed by the RAG memory layer, so this maintenance discipline does not surface from the file itself. For agents doing frontend work: the doc is authoritative for visual identity and is changed first; expanding the public prop APIs of the spec'd presentational components (the store-free atoms/molecules/organisms) to add a feature re-introduces doc/code drift, so feature logic lives in the `App.tsx` connected wrappers instead.

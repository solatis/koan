---
title: ReviewPanel.tsx imported react-markdown directly, bypassing the Md mermaid-routing
  wrapper
type: lesson
created: '2026-04-29T09:08:56Z'
modified: '2026-04-29T09:08:56Z'
related:
- 0121-visualization-framework-adopted-c4-l1-l3-mermaid.md
---

This entry records a frontend rendering bug in koan's artifact viewer (`frontend/src/components/organisms/ReviewPanel.tsx`). On 2026-04-29, Leon reported that mermaid fenced blocks in artifacts (e.g. a `sequenceDiagram` in a generated `core-flows.md`) displayed as raw markup instead of inline SVG. Investigation found that ReviewPanel imported `ReactMarkdown` from `react-markdown` directly and rendered with `<ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>`. The project has a `<Md>` wrapper at `frontend/src/components/Md.tsx` that routes `className === 'language-mermaid'` fences to a `<MermaidBlock>` SVG renderer; all other markdown surfaces in the frontend (`MemoryRoutes.tsx`, `CurationTakeover.tsx`, `SteeringBar.tsx`, `KoanToolCard.tsx`) already composed `<Md>`. ReviewPanel was the sole outlier.

Root cause: when `<Md>` was extended with mermaid support during the visualization-framework adoption work in late April 2026, existing direct-`react-markdown` callers were not audited or migrated as part of that change. The new routing reached every `<Md>`-composing surface but silently failed in the un-migrated ones.

Fix applied 2026-04-29: Leon's plan replaced the direct `ReactMarkdown` usage in `ReviewPanel.tsx` with `<Md>{content}</Md>` and updated the file-header JSDoc to describe the new path. A grep audit of `from 'react-markdown'` across `frontend/src/` confirmed the post-fix invariant -- `frontend/src/components/Md.tsx` is the only place `react-markdown` is imported.

Leon endorsed a project rule from this fix: `<Md>` is the single `react-markdown` entry point in the koan frontend. Future markdown-rendering surfaces should compose `<Md>` rather than introduce a competing direct import; doing so bypasses any future renderer extensions.

Generalized lesson: when introducing a wrapper component over a shared library to add cross-cutting behavior, audit and migrate all existing direct-import callers in the same change. One un-migrated caller silently regresses the new behavior on its surface, and the regression stays invisible until a user reports it.

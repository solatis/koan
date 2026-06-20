---
title: Removing a dead frontend feature in koan is a dependency-tree cascade, not
  a single-file delete
type: lesson
created: '2026-06-19T11:19:08Z'
modified: '2026-06-19T11:19:08Z'
---

When koan's curation approval UI was retired, the plan named only the top-level components to delete (the takeover organism and its page component) but deleting them orphaned a chain of molecules used exclusively by that UI (a decision pill, an operation badge, an overall-feedback textarea, a rationale block, a diff pane), plus those components' catalog sections in docs/design-system.md. The first implementation pass left the orphaned molecules and stale docs in place; a reviewing pass caught the gap by running a per-component orphan check -- rg -l "\bNAME\b" frontend/src, where a component whose only match is its own .tsx/.css is dead -- and a follow-up remediation pass deleted the cascade. Root cause: planning named the top-level components to remove without tracing their full import/dependency subtree, so the exclusive descendants were missed. Prevention: when removing a frontend feature in koan, trace the deleted components' full dependency subtree and delete every descendant that becomes zero-importer (verify each with rg -l excluding the component's own files), and grep docs/design-system.md for each deleted component's catalog section; keep components that still have a surviving importer (shared) and leave pre-existing unrelated orphans out of scope.

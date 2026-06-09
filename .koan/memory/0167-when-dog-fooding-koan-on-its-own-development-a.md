---
title: When dog-fooding koan on its own development, a long-lived daemon serves stale
  committed code while edits sit in the working tree
type: lesson
created: '2026-06-04T14:20:14Z'
modified: '2026-06-04T14:20:14Z'
related:
- 0012-koan-is-dog-fooded-on-its-own-development-meta.md
---

koan is developed using koan, so a running koan daemon can be exercising the code as last committed while the change under development sits uncommitted in the working tree. During the agent-layer work this produced observed behavior that did not match the code being edited, because the long-lived daemon never reloaded the working-tree changes. Root cause: a long-lived process does not pick up source edits until it is restarted, and the dog-fooding setup makes it easy to mistake the daemon's behavior for evidence about the current code. Prevention: restart the koan daemon to pick up working-tree changes before treating its behavior as evidence; a long-lived daemon's behavior reflects the code it booted with, not the code on disk.

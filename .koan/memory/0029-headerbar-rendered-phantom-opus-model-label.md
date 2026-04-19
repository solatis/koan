---
title: HeaderBar rendered phantom 'opus' model label -- destructuring default masked
  absent orchestrator state
type: lesson
created: '2026-04-16T11:29:34Z'
modified: '2026-04-16T11:29:34Z'
---

The `HeaderBar` organism in `frontend/src/components/organisms/HeaderBar.tsx` was found on 2026-04-16 to display 'opus' in the titlebar whenever no orchestrator was running. The user reported that when no primary agent was active, the model section should be empty. Investigation identified the root cause: the `orchestratorModel` parameter used a destructuring default `= 'opus'` (line 49). `App.tsx` correctly computed `orchestratorModel: primary?.model ?? undefined` -- returning `undefined` when `agents` contained no entry with `isPrimary: true`. However, the destructuring default silently substituted `'opus'` for `undefined`, making the prop appear present in all cases. The prop was already typed `orchestratorModel?: string` in `HeaderBarProps`, making the optionality semantically correct but defeated at the call site. On 2026-04-16, the fix was applied: the `= 'opus'` default was removed from the destructuring parameter, and the `hb-orchestrator` div was wrapped in `{orchestratorModel && (...)}` to suppress the entire section (both the `StatusDot` atom and the `hb-model` span) when no model was known.

---
title: 'koan project dependency pin policy: exact pins (==X.Y.Z) always, unless impossible'
type: procedure
created: '2026-05-08T07:30:55Z'
modified: '2026-05-08T07:30:55Z'
---

This entry records the koan project's dependency-pin policy in `pyproject.toml`. On 2026-05-08, during a plan-spec follow-up question about how to bump `claude-agent-sdk`, user stated the project rule: "We only ever do exact pins, unless specifically impossible / inconvenient / unsuitable." User explicitly flagged this as a fact for the curation phase to memorialize.

The procedure: when adding or bumping a dependency in `pyproject.toml` `[project] dependencies` (or any equivalent dependency-listing surface in koan), use the exact-equality operator `==X.Y.Z` rather than a lower-bound floor (`>=`), a compatible-release operator (`~=`), or a version range. Example application: `claude-agent-sdk==0.1.76` was set on 2026-05-08; `uv lock` was run after the `pyproject.toml` edit so `uv.lock` recorded the exact resolved tree. `uv.lock` is not edited by hand.

Exceptions are limited to the user's stated grounds -- "specifically impossible, inconvenient, or unsuitable" -- not aesthetic preference. Rationale stated by user: exact pins make builds reproducible across developer machines, CI, and production. The policy trades the cost of explicit upgrade work (one `pyproject.toml` edit per bump) for guaranteed consistency.

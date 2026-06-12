---
title: 'Two koan installs coexist during the refactoring: ~/koan-stable worktree (old,
  ~/.koan/config.json) and this repo (new, ~/.koan/config.yaml + master.key)'
type: context
created: '2026-06-11T03:20:42Z'
modified: '2026-06-11T03:20:42Z'
related:
- 0180-run-and-inspect-koan-through-the-project-venv.md
- 0187-koan-user-config-migrated-from-json-configjson.md
---

While the provider/config refactoring is in progress, two koan installations coexist on the developer machine and share the `~/.koan/` state directory. The old, stable install is a git worktree at `~/koan-stable`; it reads and writes `~/.koan/config.json`. The new install is this repository; it writes `~/.koan/config.yaml` and uses the Fernet `~/.koan/master.key` for the encrypted CredentialStore. Both `config.json` and `config.yaml` are present in `~/.koan/` at the same time. This matters because an agent inspecting `~/.koan/` or resolving an interpreter can silently hit the stable worktree instead of this repo -- for example `python3` resolves to `~/koan-stable/.venv` (a divergent pydantic-ai), and the wrong config file can be read. Inspect this repository's `.venv`/`.env` and `~/.koan/config.yaml`, not the `~/koan-stable` worktree or `~/.koan/config.json`. The arrangement is transitional and exists only until the stable install is retired.

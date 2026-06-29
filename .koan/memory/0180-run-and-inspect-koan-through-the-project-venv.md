---
title: Run and inspect koan through the project venv (.venv/.env, pydantic-ai 2.0.0);
  the system python3 has a divergent older pydantic-ai
type: procedure
created: '2026-06-07T07:54:43Z'
modified: '2026-06-27T08:17:23Z'
related:
- 0164-plan-built-on-the-pydanticai-v2-beta-assumed-its.md
---

koan pins `pydantic-ai-slim==2.0.0` in `pyproject.toml`, and the project virtualenvs `.venv/` and `.env/` have that version installed; `uv.lock` is the lockfile (regenerate with `uv lock`, never hand-edit). The pin was bumped from the `2.0.0b6` pre-release to the stable `2.0.0` release on 2026-06-27; per the pydantic-ai changelog there were no breaking changes since the betas (all V2 breaking changes landed at 2.0.0b1), so the bump was a pin + lockfile change with no code adaptation required. The machine's system `python3`, however, resolves `pydantic_ai` to an older divergent line (observed as `1.85.1`), whose provider/model classes and constructor signatures differ from 2.x. When inspecting pydantic-ai symbols or running koan's tests, invoke `.venv/bin/python` (or `uv run`); a bare `python3 -c "import pydantic_ai"` silently reads the divergent system package and reports an API surface that does not match the code koan runs against, misleading any plan built on it.

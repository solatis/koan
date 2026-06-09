---
title: Run and inspect koan through the project venv (.venv/.env, pydantic-ai 2.0.0b5);
  the system python3 has a divergent pydantic-ai 1.85.1
type: procedure
created: '2026-06-07T07:54:43Z'
modified: '2026-06-07T07:54:43Z'
related:
- 0164-plan-built-on-the-pydanticai-v2-beta-assumed-its.md
---

koan pins `pydantic-ai-slim==2.0.0b5` (a pre-release) in `pyproject.toml`, and the project virtualenvs `.venv/` and `.env/` both have that version installed. The machine's system `python3`, however, resolves `pydantic_ai` to a stable `1.85.1`, whose provider/model classes and constructor signatures differ from the beta. When inspecting pydantic-ai symbols or running the test suite for koan, invoke `.venv/bin/python` (or `.env/bin/python`); a bare `python3 -c "import pydantic_ai"` silently reads the 1.x package and reports an API surface that does not match the code koan runs against, misleading any plan built on it.

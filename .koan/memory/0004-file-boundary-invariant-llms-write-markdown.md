---
title: File boundary invariant -- LLMs write markdown, driver writes JSON
type: decision
created: '2026-04-16T07:14:03Z'
modified: '2026-06-20T03:26:14Z'
---

The file boundary invariant is a load-bearing architectural constraint in koan governing file ownership across the system's actors, established by Leon in the initial design (documented in `docs/architecture.md` as Invariant 1). The rule: LLM subagents write markdown files only; the koan driver (`koan/driver.py`) reads and writes JSON state files exclusively; the in-process koan tool layer (`koan/tools/`, e.g. `koan_tools.py`) bridges both worlds by writing JSON state (for the driver) and templated markdown for LLMs in the same operation. Leon's rationale: if an LLM writes a JSON file, schema drift and parse errors in the payload become runtime failures in the deterministic driver, whereas markdown is forgiving. The invariant is enforced structurally -- planning-role subagents have write access scoped to the run directory (`~/.koan/runs/<id>/`) but no mechanism to produce JSON state files, and the driver reads JSON state files and exit codes only, never parsing markdown.

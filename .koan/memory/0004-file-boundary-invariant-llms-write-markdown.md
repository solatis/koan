---
title: File boundary invariant -- LLMs write markdown, driver writes JSON
type: decision
created: '2026-04-16T07:14:03Z'
modified: '2026-04-16T07:14:03Z'
---

The file boundary invariant is a load-bearing architectural constraint in koan governing file ownership across the system's actors. On 2026-02-10, Leon established this rule in the koan initial design (documented in `docs/architecture.md` as Invariant 1). The rule: LLM subagents write markdown files only; the koan driver (`koan/driver.py`) reads and writes JSON state files exclusively; tool code in `koan/web/mcp_endpoint.py` bridges both worlds by writing JSON state (for the driver) and templated markdown status files (for LLMs) in the same operation. Leon's stated rationale: if an LLM writes a JSON file, schema drift and parse errors in the payload become runtime failures in the deterministic driver, while markdown is forgiving. The invariant is enforced structurally -- planning-role subagents have write access scoped to the run directory (`~/.koan/runs/<id>/`) but no mechanism to produce JSON state files, and the driver reads JSON state files and exit codes only, never parsing markdown.

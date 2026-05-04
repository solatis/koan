---
title: 'Mermaid sequenceDiagram syntax hazards: no `;` in Note bodies; `<br>` for
  multi-line Notes'
type: procedure
created: '2026-04-29T09:09:05Z'
modified: '2026-04-29T09:09:05Z'
related:
- 0121-visualization-framework-adopted-c4-l1-l3-mermaid.md
---

This entry documents two parser hazards in mermaid `sequenceDiagram` syntax that affect LLM-generated diagrams in koan's planning artifacts (`core-flows.md`, `tech-plan.md`). On 2026-04-29, Leon surfaced a parse-error reproduction in a generated `core-flows.md`: a line `Note over A, B: Two unrelated entry points; mutually exclusive per agent` failed with `Parse error on line 9 ... Expecting '()', 'SOLID_OPEN_ARROW', 'DOTTED_OPEN_ARROW', 'SOLID_ARROW', ...` pointing at the next line.

Root cause: in mermaid's `sequenceDiagram` grammar, `;` is a statement separator (the alternative to a newline). When `;` appears inside a `Note over` body, it terminates the Note mid-sentence; the remainder of that line parses as a new statement expecting an arrow token, and on failure the parser eats the next line still searching for the arrow -- producing the misleading "Expecting SOLID_ARROW" error pointing at the line below.

Two hazards captured in `docs/visualization-system.md` section 8 ("Mermaid syntax hazards") on 2026-04-29:

- Do not use `;` inside `Note over`, `Note left of`, or `Note right of` bodies, or inside message labels (the text after the `:` in `A->>B: text`). Use `,`, `--`, or split into two separate Notes.
- For multi-line Notes, use the `<br>` HTML break tag rather than embedding a raw newline; mermaid does not parse multi-line Note bodies across raw newlines.

Why this matters for LLM-generated content specifically: LLMs naturally produce prose with semicolons (parenthetical clauses, list separators). Without explicit guidance in the generation prompt, the LLM emits parser-breaking content, producing a frozen artifact that fails to render until a downstream reader notices.

The rule was inlined into the `PHASE_ROLE_CONTEXT` strings of `koan/phases/core_flows.py` and `koan/phases/tech_plan_spec.py` (the two phases that emit `sequenceDiagram` content per the visualization-framework slot mapping), each as a 7-line `## Mermaid syntax hazards` subsection that cross-references `docs/visualization-system.md` section 8. Two presence tests in `tests/test_phase_guidance.py` (`test_core_flows_role_context_includes_mermaid_syntax_hazards`, `test_tech_plan_spec_role_context_includes_mermaid_syntax_hazards`) assert the heading, the semicolon mention, the `<br>` mention, and the doc cross-reference, guarding against silent regression of the inlined guidance.

Procedure for future agents: any new phase module that emits mermaid `sequenceDiagram` content should follow the same pattern -- inline the hazards rule in `PHASE_ROLE_CONTEXT` with a cross-reference to `docs/visualization-system.md` section 8, and add a parallel presence test in `tests/test_phase_guidance.py`.

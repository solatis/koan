---
title: 'Visualization framework adopted: C4 L1-L3 + Mermaid + slot-based templating
  with whether/what fixed in templates'
type: decision
created: '2026-04-28T15:55:09Z'
modified: '2026-04-28T15:55:09Z'
---

This entry documents the adopted visualization framework for diagrams in koan's planning artifacts (Core Flows, Tech Plan, Ticket Bundle). On 2026-04-28, Leon initiated the plan workflow that integrated mermaid rendering into the frontend `<Md>` component as groundwork for the framework; `docs/visualization-system.md` (committed prior) thereby became koan's canonical diagram doctrine via the initiative's intake. The framework was grounded in four corpus papers Leon cited: CIAO (system-level architecture from GitHub repos using C4 + ISO/IEC/IEEE 42010), MASC4 (C4 L1-L3 from system briefs via LLM agents), VisDocSketcher (Mermaid sketches from Jupyter notebooks), and ArchView (LLM-generated architecture views across 340 repositories).

Four key constraints govern the framework. (1) Levels: C4 L1 (Context), L2 (Container), L3 (Component) only; L4 (Code) deferred per MASC4. (2) Notation: Mermaid only -- chosen over PlantUML, DOT, Graphviz, ASCII because Mermaid renders inline in markdown without external tooling. (3) Decision authority is split: templates decide *whether* a diagram appears in a given location and *what kind*; the LLM decides only *which specific instances* populate the slot and *whether to suppress* per count-based rules. (4) Grounding: no component, actor, or state may appear that is not in the bounded inputs (Epic Brief / Core Flows / codebase analysis notes).

The five-type diagram catalog: CTX (`flowchart`, L1), CON (`flowchart`, L2), CMP (`classDiagram` or `flowchart`, L3), SEQ (`sequenceDiagram`), STT (`stateDiagram-v2`). Document-to-slot mapping locked at adoption: Core Flows -> SEQ per flow (default required); Tech Plan -> CON for Architectural Approach (required), CMP for any in-scope component, SEQ for non-trivial cross-component flows, STT for entities with >=3 states + conditional transitions; Ticket Bundle -> dependency `flowchart` when >=3 tickets. Epic Brief and individual Tickets intentionally have no diagrams. Suppression thresholds per slot are documented in `docs/visualization-system.md` §5.

Out of scope at adoption: deployment diagrams (ArchView reports automated quality drops), package/dependency diagrams (low-value), ER diagrams (data models stay as fenced schema code), L4 code-level diagrams, non-Mermaid notations (require external rendering), auto-update on doc edit, cross-document glossary/shared vocabulary.

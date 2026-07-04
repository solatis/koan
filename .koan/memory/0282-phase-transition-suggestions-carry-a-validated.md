---
title: Phase-transition suggestions carry a validated phase field and no command text;
  koan_suggest_next rejects invalid phase ids with the recoverable envelope
type: decision
created: '2026-07-04T01:32:03Z'
modified: '2026-07-04T01:32:03Z'
related:
- 0280-mechanical-ui-phase-transitions-post-apiphase-and.md
---

Suggestion schema for the phase-boundary hand-back -- Leon decided that suggestions denoting phase transitions carry an additive `phase: str` field end-to-end (`Suggestion` projection model in `koan/projections.py`, `build_phase_suggestions` in `koan/lib/workflows.py`, frontend `Suggestion` types) and drop their `command` text entirely: the transition itself is the whole meaning, and the frontend routes clicks on the metadata (non-empty `phase` -> mechanical `POST /api/phase`; absent -> chat-draft path, unchanged). `suggest_next_core` in `koan/tools/koan_tools.py` validates any suggestion carrying a non-empty `phase` against the active workflow via `is_valid_transition` (plus the literal `"done"`), returning the recoverable `{"ok": false}` envelope with code `invalid_suggestion_phase` and storing nothing on failure -- orchestrator-authored phase suggestions MUST be valid because a click on one becomes an unguarded-by-the-LLM mechanical mutation. Free-text suggestions (no `phase` key) pass through unvalidated. Yolo mode, which drives itself off suggestion commands, synthesizes "Proceed to the {phase} phase." for command-less phase suggestions in `_yolo_yield_response` (`koan/agents/loop.py`). Alternatives rejected: frontend inference by matching suggestion ids against workflow phase names (implicit and collision-prone -- a free-text suggestion whose id happened to equal a phase name would be misrouted); a separate fixed UI element for phase buttons (duplicates the suggestion surface); buffering the dropped command text as a user message into the new phase's first turn (redundant -- the transition carries the meaning).

---
title: yolo mode -- non-interactive auto-answer for the loop hand-back and koan_ask_question
type: decision
created: '2026-04-19T08:10:27Z'
modified: '2026-06-05T01:55:18Z'
related:
- 0158-koanyield-removed-the-agent-loops-terminal-text.md
- 0061-directedphases-fixed-phase-sequence-for-eval.md
---

koan's yolo mode (`app_state.server.yolo`) is a non-interactive auto-answer mode for unattended runs -- it backs the eval runner and any headless invocation. When yolo is on, every point where the orchestrator would block for the user resolves immediately. At the loop's terminal-text hand-back, instead of parking, the loop synthesizes the next turn's prompt in `koan/agents/loop.py`: if `directed_phases` is set, `_directed_yolo_response` steers toward the next phase in the fixed sequence; otherwise `_yolo_yield_response` picks the command of the first recommended non-done suggestion, then the first non-done suggestion, then `"proceed"`. For `koan_ask_question`, `_yolo_ask_answer` synthesizes an answer per question -- the recommended option's label, or `"use your best judgement"` when no option is recommended, giving the orchestrator latitude rather than forcing an arbitrary pick. Leon chose suggestion-driven responses and a judgement fallback over fixed strings so an unattended run still follows the workflow's intended path. The interaction projection events (the hand-back and `questions_asked`) are still emitted before the auto-answer resolves, so UI cards appear and close immediately. Directed mode exists to give eval runs explicit phase-sequence control without relying on the orchestrator's interpretation of suggestion commands.

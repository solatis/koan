---
title: New blocking user-choice interactions in koan reuse the ask/elicitation machinery
  via a new enqueue_interaction type, not a parallel projection surface
type: decision
created: '2026-06-19T11:19:15Z'
modified: '2026-06-19T11:19:15Z'
---

When koan added an operational escalation prompt (offering Abort / Wait-longer / Proceed-unreviewed when provider retries are exhausted), the first plan proposed a parallel surface: a dedicated projection Focus variant, new raised/resolved events, a dedicated HTTP endpoint, and a new frontend panel. Adversarial review of the plan rejected this as duplicating working machinery. koan's existing ask interaction already renders 'a question with options' through enqueue_interaction (koan/web/interactions.py) -> the questions_asked event -> a QuestionFocus on the projection -> the ElicitationPanel, and resolves through /api/interact (api_interact in koan/web/app.py). The adopted design adds ONLY a new enqueue_interaction TYPE string: its _emit_interaction_request branch emits the existing questions_asked event (reusing QuestionFocus and ElicitationPanel), and api_interact's active-interaction guard is widened to accept the new type. Rationale: reusing the existing surfacing and resolution path is far less code and risk than a parallel surface. Rejected alternative: a parallel Focus variant + dedicated events + dedicated endpoint + a new panel (working-machinery duplication). Durable rule for future blocking user-choice interactions in koan: add an enqueue_interaction type and reuse questions_asked / QuestionFocus / ElicitationPanel / api_interact rather than building parallel projection, UI, or endpoint surfaces.

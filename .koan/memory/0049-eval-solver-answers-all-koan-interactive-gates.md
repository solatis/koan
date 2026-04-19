---
title: Eval Solver answers all koan interactive gates with a fixed message, not a
  surrogate LLM
type: decision
created: '2026-04-17T12:06:18Z'
modified: '2026-04-17T12:06:18Z'
---

The koan eval Solver's approach to interactive phase handling was established on 2026-04-17 during the test suite overhaul planning session. During a live koan workflow run, the orchestrator calls `koan_yield` (which blocks until a user message arrives via `POST /api/chat`) and `koan_ask_question` (which blocks until answers arrive via `POST /api/answer`). In the eval context these gates would block indefinitely. Leon decided that the Solver in `evals/solver.py` answers every interactive gate with a fixed message: "Please use your best judgment and pick whichever option you think is best." The orchestrator self-selects from available options. Leon rejected the alternative of a surrogate-user LLM -- a second LLM impersonating the user and answering questions on the fly -- because it would add LLM API cost and non-determinism to the eval without proportional signal gain at this early stage of the framework.

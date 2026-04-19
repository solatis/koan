---
title: Code-comment vs memory-entry filter -- COMMENT classification and executor
  rationale comments
type: decision
created: '2026-04-17T04:22:11Z'
modified: '2026-04-17T04:22:11Z'
---

The curation phase's COMMENT classification in `koan/phases/curation.py` was added on 2026-04-17 to filter implementation-specific knowledge out of the koan memory store. The user identified that entries like "backend.py exposes search_candidates and rerank_results separately" recorded knowledge that would serve agents better as code comments next to the relevant functions. The design introduced a two-part strategy: (1) a COMMENT classification in the curation phase's `PHASE_ROLE_CONTEXT` that applies a test question -- "Would a code comment next to the relevant function give a future agent the same benefit?" -- to filter candidates that describe single-function rationale, parameter defaults, or single-module patterns; (2) a "Rationale comments" directive in `koan/phases/executor.py` step 3 instructing executors to write brief 1-3 line "why" comments at code locations when making implementation choices. Alternative considered: relying solely on the existing "What not to capture" guidance without a formal classification -- rejected because it lacked a mechanical discrimination test and did not redirect the knowledge to code comments.

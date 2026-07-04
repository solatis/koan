---
title: Mechanical-resume sentinel encoded as a claim flag on InteractionState, set
  before the route's first await, because a future result value cannot close the concurrent-resolver
  race
type: decision
created: '2026-07-04T01:32:03Z'
modified: '2026-07-04T01:32:03Z'
related:
- 0068-blocking-mcp-tool-handlers-that-park-on-per-run.md
- 0016-steering-vs-phase-boundary-message-routing-dual.md
- 0280-mechanical-ui-phase-transitions-post-apiphase-and.md
---

Agent-loop resume path for mechanical phase transitions -- the sentinel that tells `run_agent_loop` "this resume was a mechanical transition, skip the model turn" is a `mechanical_resume: bool` field on `InteractionState` in `koan/state.py`. The flag doubles as a *claim*: `api_set_phase`/`api_set_workflow` set it synchronously after all guards and before their first `await`, and both other live `yield_future` resolvers (`api_chat` and `api_artifact_comment` in `koan/web/app.py`) defer incoming messages to the steering queue while it is set. This closes the race where a chat message or artifact comment resolves `yield_future` while `apply_set_phase` is suspended on its internal `run-state.json` I/O. Alternatives rejected: a distinguished `yield_future` result value (cannot close the race -- the future remains up for grabs during the async apply, and the loop's resume path discards the future's value by contract); a second dedicated future (violates the established reentry-guard discipline that per-run futures are never reassigned while pending). The flag is cleared by the loop's sentinel branch on resume and by every route error path after the claim; the sentinel branch also defensively drains any raced `user_message_buffer` contents into the steering queue rather than stranding them for stale delivery on the next resume. The wrong approach is resolving `yield_future` with a special value and hoping consumers check it -- the resume-value contract discards it, and the claim window would stay open.

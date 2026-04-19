---
title: 'Steering vs phase-boundary message routing: dual-queue design'
type: decision
created: '2026-04-16T08:37:51Z'
modified: '2026-04-16T08:37:51Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
- 0002-step-first-workflow-pattern-boot-prompt-is.md
---

The user message routing system in koan (`koan/web/mcp_endpoint.py`, `docs/ipc.md` -- Chat Message Delivery section) was designed around two independent message queues. On 2026-03-29, Leon documented the distinction in `docs/ipc.md`. Leon designed phase-boundary messages (sent while `koan_yield` is blocking and `app_state.yield_future` is set) to be routed to `user_message_buffer` and returned directly as the `koan_yield` MCP tool result when the future resolves. Leon designed steering messages (sent while the orchestrator is mid-step and `yield_future` is `None`) to be routed to `steering_queue` and appended to the next outgoing tool response via `_drain_and_append_steering()`, so the LLM integrates them without abandoning the current step. Leon designated both queues as atomically drained and independent to prevent double-delivery: `drain_user_messages()` clears `user_message_buffer` and `drain_steering_messages()` clears `steering_queue`. The `POST /api/chat` endpoint inspects `yield_future` at the moment of message receipt to determine which queue to route to.

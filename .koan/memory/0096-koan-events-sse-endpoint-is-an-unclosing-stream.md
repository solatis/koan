---
title: Koan /events SSE endpoint is an unclosing stream; blocking httpx.get hangs
  forever
type: lesson
created: '2026-04-23T16:54:58Z'
modified: '2026-04-23T16:54:58Z'
---

This lesson was distilled on 2026-04-23 while Leon debugged a hang in the new subprocess-based eval runner that polled koan's HTTP API to harvest projection state.

Context. Koan's `/events` endpoint is a Server-Sent Events streaming response implemented in `koan/web/sse.py`. It is designed for the browser dashboard to maintain a long-lived connection -- the server never closes the connection voluntarily; it emits events as they occur and keeps the response open indefinitely.

Failure mode. `httpx.get(url + "/events")` and equivalent `requests.get` calls are blocking: the client waits for the response body to complete before the call returns. On an unclosing stream the body never completes and the call hangs forever. The harvest code appeared to deadlock waiting for the subprocess to finish, but the subprocess was already idle; the hang was the SSE poll on the harness side.

Fix adopted on 2026-04-23. Leon replaced the blocking call with streaming reads: `async with httpx.AsyncClient() as client: async with client.stream("GET", url + "/events") as response: async for line in response.aiter_lines():`. The harness reads events until it observes the projection snapshot it needs, then breaks out of the iterator and exits the `stream` context manager, which closes the client side of the connection. This is the only safe way to consume `/events` from a non-browser client.

Lesson for future koan-harness work: any HTTP endpoint in koan whose purpose is streaming (`/events`, future websocket bridges) must be consumed with streaming-reader idioms, never with one-shot blocking GET. The contract is not enforced by the framework; the only signal is the endpoint's purpose.

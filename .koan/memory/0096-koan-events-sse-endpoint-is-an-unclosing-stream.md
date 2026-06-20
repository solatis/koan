---
title: Koan /events SSE endpoint is an unclosing stream; blocking httpx.get hangs
  forever
type: lesson
created: '2026-04-23T16:54:58Z'
modified: '2026-06-20T03:38:49Z'
---

koan's `/events` endpoint is a Server-Sent Events streaming response in `koan/web/app.py`: it is designed for the browser dashboard to hold a long-lived connection -- the server never closes it voluntarily, emitting events as they occur and keeping the response open indefinitely. Failure mode: `httpx.get(url + "/events")` and equivalent `requests.get` calls are blocking -- the client waits for the response body to complete before returning, and on an unclosing stream the body never completes, so the call hangs forever. A non-browser harvest harness appeared to deadlock waiting for the koan subprocess to finish, but the subprocess was already idle; the hang was the SSE poll on the harness side. Fix: Leon replaced the blocking call with streaming reads -- `async with httpx.AsyncClient() as client: async with client.stream("GET", url + "/events") as response: async for line in response.aiter_lines():` -- reading events until the needed projection snapshot is observed, then breaking out of the iterator and exiting the `stream` context manager, which closes the client side. Lesson: any koan HTTP endpoint whose purpose is streaming (`/events`, future websocket bridges) must be consumed with streaming-reader idioms, never a one-shot blocking GET. The contract is not enforced by the framework -- the only signal is the endpoint's purpose.

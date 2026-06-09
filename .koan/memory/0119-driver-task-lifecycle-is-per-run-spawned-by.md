---
title: Driver task lifecycle is per-run, spawned by api_start_run; lifespan no longer
  owns it; RunState.driver_task is the active-run guard authority
type: decision
created: '2026-04-28T04:53:44Z'
modified: '2026-04-28T04:53:44Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

This entry documents the driver task lifecycle in koan's web entry path (`koan/web/app.py`, `koan/driver.py`, `koan/state.py`). On 2026-04-28, Leon redirected the driver task lifecycle from "one task created in the Starlette lifespan that lives for the server's lifetime" to "one task created per workflow run by `api_start_run`". The bug that surfaced the change: `driver_main` was created exactly once during `create_app`'s lifespan, awaited `app_state.run.start_event.wait()` once, spawned the orchestrator via `spawn_subagent`, and returned -- after the first workflow completed, the task was dead and the second `start_event.set()` from `/api/start-run` had no listener, so submitting a new run returned HTTP 200 but produced no orchestrator process and no log activity. The fix: `koan/state.py:RunState` lost `start_event: asyncio.Event` and gained `driver_task: asyncio.Task | None = None`; the lifespan no longer creates the driver task; `api_start_run` creates it via `asyncio.create_task(driver_main(st))` after committing run-scoped state and assigns the handle to `st.run.driver_task`; a 409 guard at the top of `api_start_run` rejects a new request whenever `st.run.driver_task is not None and not st.run.driver_task.done()`. Leon endorsed this shape (Option B in the run's intake) over the alternative loop-in-driver_main shape (Option A: `while True: await start_event.wait(); start_event.clear(); ...`) because Option A preserves the lifespan-scoped singleton lifetime that future concurrent multi-run support will need to undo, while Option B aligns the driver task lifetime with the workflow run it serves -- the same shape concurrent multi-run will require regardless. Done-callbacks on the task were rejected: `task.done()` is the authoritative check, so the guard does not need an `add_done_callback` to none-out `driver_task`.

---
title: Lifespan-scoped one-shot driver task silently dropped second-run launches
type: lesson
created: '2026-04-28T04:53:58Z'
modified: '2026-04-28T04:53:58Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
- 0119-driver-task-lifecycle-is-per-run-spawned-by.md
---

This entry records a failure in koan's web server lifecycle (`koan/web/app.py:create_app` Starlette lifespan, `koan/driver.py:driver_main`). On 2026-04-28, Leon reported that after a workflow completed and the "new run" screen reappeared, submitting a second run produced no orchestrator process and no console activity in either the frontend UI or the backend log -- `POST /api/start-run` returned 200 but nothing happened thereafter. Root cause identified during intake: the driver task was spawned exactly once at server startup via `asyncio.create_task(driver_main(app_state))` inside `create_app`'s `@asynccontextmanager async def lifespan(app)`. The body of `driver_main` followed wait/run/return semantics: `await app_state.run.start_event.wait()` once, `await spawn_subagent(...)`, push `workflow_completed`, return. After the first workflow ran, the task was done and the second `start_event.set()` from `api_start_run` had no listener; the asyncio Event also was never `.clear()`ed, but the absent listener was the proximate failure. Generalizable lesson: any lifespan-scoped asyncio task that follows wait/run/return semantics is silently single-use -- the task ends after the first activation, the lifespan does not respawn it, and the next set/put/notify operation has no consumer. Two valid shapes prevent the regression: a `while True` loop inside the lifespan task (with the wakeup primitive cleared each iteration), or per-trigger task creation at the trigger site. Leon chose the latter on 2026-04-28 (recorded separately in `0119-driver-task-lifecycle-is-per-run-spawned-by.md`); the former was rejected because it preserves the lifespan-scoped singleton shape future concurrent multi-run support will need to undo.

---
title: Commit uploaded files into the active run directory at HTTP submission time,
  not at tool-drain time
type: procedure
created: '2026-04-24T16:39:20Z'
modified: '2026-04-24T16:39:20Z'
---

This entry records the commit-to-run pattern for attachment-bearing HTTP endpoints in koan (`koan/web/app.py`, `koan/web/uploads.py`). On 2026-04-24, Leon established that uploaded files move from the server-lifetime tempdir into `<run_dir>/uploads/<id>/<filename>` at HTTP-submission time via `commit_to_run(state, upload_ids, run_dir)`, not at tool-drain time inside the MCP handler. Every endpoint that accepts `attachments: list[str]` calls `commit_to_run` immediately after validating the request body and before persisting the message / answer / decision. Tool handlers that later emit the attachments (e.g. `koan_yield`, `koan_ask_question`, `koan_memory_propose`) only call `resolve_upload(state, id)` and read `record.path`. Rationale: commit at submission keeps `record.path` stable for the lifetime of the attachment, lets the orchestrator use deterministic filesystem paths during fastmcp's `File(path=...)` content-block construction, and ties attachment lifetime to the run directory so `shutil.rmtree(run_dir)` on session delete cleans everything uniformly. Defensive rule: if `st.run.run_dir is None` at HTTP submission and the request carries attachments, return 409 `no_run`. Exception: `POST /api/start-run` creates the run directory itself and commits into it before emitting `run_started`. Unknown IDs are silently dropped by `commit_to_run` (logged at WARN); callers that persist the delivered set use `list(committed.keys())` (the returned dict) rather than the raw input to filter stale IDs out of the delivery contract.

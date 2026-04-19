---
title: koan memory sync uses SHA-256 content hash, not mtime, as change-detection
  invariant
type: decision
created: '2026-04-16T13:32:18Z'
modified: '2026-04-16T13:32:18Z'
---

The sync layer in `koan/memory/retrieval/index.py` was designed on 2026-04-16, with the user confirming the design in plan-review, to detect changes to `.koan/memory/NNNN-*.md` entry files using SHA-256 content hashes stored as a `content_hash` column in the LanceDB table, rather than file modification timestamps (mtime).

Two alternatives were considered and rejected by the plan author:
- **mtime**: git operations (branch checkout, `git pull`, `git stash`) update file mtimes without changing content; `touch` changes mtime without changing content. An mtime-based sync would spuriously re-embed files after routine git operations, wasting Voyage AI embedding API calls.
- **A separate metadata sidecar file** (e.g., a JSON file tracking hashes alongside the index): rejected in favor of storing hashes as a LanceDB column, keeping the index fully self-contained with no external tracking file.

The hash computation uses `hashlib.sha256(path.read_bytes()).hexdigest()` stored in the `content_hash` column of the LanceDB `entries` table.

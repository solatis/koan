---
title: New docs/ files must avoid case-collision with the per-directory AGENTS.md
  conventions file
type: procedure
created: '2026-05-02T07:23:14Z'
modified: '2026-05-02T07:23:14Z'
---

The koan repository uses per-directory `AGENTS.md` conventions files at the project root, in `docs/`, in `frontend/`, and in `frontend/src/components/`. Each holds the conventions for agents working in that directory. On 2026-05-02, during intake re-planning of cancelled documentation work for the Claude Agent SDK migration, the agent discovered that the original `plan-milestone-3.md` (finalized 2026-04-30) prescribed writing the new Agent reference at `docs/agents.md`. On macOS's case-insensitive default filesystem (HFS+ and APFS in their default configuration), `docs/agents.md` and `docs/AGENTS.md` resolved to the same inode -- `diff` returned no output, confirming identical content. Writing `docs/agents.md` would have overwritten the conventions file. User directed the rename to `docs/agent-protocol.md` (selected from four alternatives offered). On the same date, user established the rule that any new file added to a directory containing an `AGENTS.md` conventions file must use a name that does not match `agents.md` in any case. The check is mechanical: a candidate filename whose lowercase form equals `agents.md` is unsafe and must be renamed. The rule applies to all directories carrying the per-directory conventions convention -- `docs/`, `frontend/`, `frontend/src/components/`, and the project root.

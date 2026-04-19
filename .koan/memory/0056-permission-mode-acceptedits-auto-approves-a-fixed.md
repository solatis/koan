---
title: --permission-mode acceptEdits auto-approves a fixed Bash subset inside --add-dir
  scope
type: context
created: '2026-04-19T06:21:23Z'
modified: '2026-04-19T06:21:23Z'
---

This entry documents permission-mode behavior for Claude subagents in koan. On 2026-04-19, during the plan-workflow Claude-CLI-flags change, Leon cited Anthropic's documentation establishing that `--permission-mode acceptEdits` auto-approves two categories of Claude Code tool calls: (1) all Write and Edit tool calls, and (2) a fixed set of filesystem Bash commands -- `mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, `sed`, optionally prefixed with safe environment variables (`LANG=C`, `NO_COLOR=1`) or wrapped in process wrappers (`timeout`, `nice`, `nohup`). Auto-approval applied only to paths inside the CLI's working directory and any directories added via `--add-dir`. Koan's Claude subagents ran in headless mode (`-p` + `--output-format stream-json`), which could not respond to interactive permission prompts, so Bash commands outside this safe subset would hang indefinitely when invoked. Leon accepted this tradeoff for the change, and the koan design chose `acceptEdits` as the unconditional permission mode for every Claude subagent (orchestrator, executor, scout). Leon also stated an intent to repurpose the `--yolo` flag into a separate non-interactive mode at a later date, at which point workflows requiring broader Bash execution could bypass the safe-subset restriction.

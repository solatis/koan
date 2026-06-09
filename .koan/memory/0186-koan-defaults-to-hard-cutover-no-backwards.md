---
title: koan defaults to hard cutover (no backwards compatibility) for code/config/format
  changes; only .koan/memory is preserved
type: procedure
created: '2026-06-08T08:25:54Z'
modified: '2026-06-08T08:25:54Z'
related:
- '0143'
- '0122'
---

koan is a solo, unreleased personal project. On 2026-06-08, while choosing how to migrate the user-config file format, Leon stated the standing rule explicitly: backwards compatibility is not required, and the ONLY thing that must be preserved across changes is the curated project memory under `.koan/memory/`. Everything else -- code interfaces, on-disk data formats, config schemas -- defaults to a clean break. When a change alters such an interface or format, do NOT add backwards-compatibility shims, migration code, dual-read/dual-format support, or deprecation aliases unless the user explicitly asks. The wrong approach is to invest in graceful migration "to be safe"; that adds complexity the project does not want while it is unreleased and single-user. The rule was applied the same day to the config migration: the JSON->YAML conversion was a hard cutover with no migration path, orphaning any existing `~/.koan/config.json` (credentials reseed from env vars on boot or are re-entered via the settings UI). The carve-out for `.koan/memory` exists because memory is curated knowledge that must survive across workflow runs, whereas code and config are regenerable.

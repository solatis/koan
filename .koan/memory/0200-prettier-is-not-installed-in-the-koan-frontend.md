---
title: prettier is not installed in the koan frontend; the global 'run prettier on
  markdown' step cannot run, so format markdown by hand
type: procedure
created: '2026-06-10T22:49:00Z'
modified: '2026-06-10T22:49:00Z'
---

`prettier` is not a dependency of the koan frontend: it is absent from `frontend/package.json` and from `frontend/node_modules/.bin/`. The user-global coding instruction to run `prettier --write` on markdown files after editing therefore cannot be satisfied in this repository -- invoking it fails with 'no such file or directory.'

When editing markdown in koan (for example `docs/design-system.md` or other `docs/` files), do not plan or depend on a prettier formatting step; format manually and match the file's existing house style. `docs/design-system.md` uses U+2014 em-dashes for sentence-level dashes rather than ASCII '--', while backtick-wrapped CSS-variable tokens such as `--status-queued` keep their ASCII double hyphen. Verbatim doc edits preserve these conventions so the file stays internally consistent.

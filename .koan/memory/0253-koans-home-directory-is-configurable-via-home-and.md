---
title: koan's home directory is configurable via --home and KOAN_HOME; config.yaml,
  master.key, and runs/ derive from it and the old path globals were removed in favor
  of explicit threading
type: decision
created: '2026-06-28T05:59:48Z'
modified: '2026-06-28T05:59:48Z'
related:
- 0213-koan-forbids-module-global-singletons-for.md
- 0178-koan-provider-api-keys-stored-in-an-encrypted.md
---

koan's per-user state directory -- historically the hardcoded `~/.koan` -- became configurable through a `--home PATH` command-line flag (available on every subcommand) and a `KOAN_HOME` environment variable, with precedence `--home` > `KOAN_HOME` > `Path.home() / ".koan"`. Leon directed this and chose that the provided path IS the state directory directly, with no `.koan` segment appended: `config.yaml`, the Fernet `master.key`, and the `runs/` directory derive as `<home>/config.yaml`, `<home>/master.key`, `<home>/runs/`. A pure resolver `resolve_koan_home(cli_home, env)` in `koan/home.py` implements the precedence -- an explicit home is `expanduser().resolve()`d, while the default branch returns the literal `Path.home() / ".koan"` unchanged.

The three import-time module globals that previously computed these paths were removed: `CONFIG_PATH` (`koan/config.py`), `MASTER_KEY_PATH` (`koan/credentials.py`), and `RUNS_DIR` (`koan/web/app.py`). The resolved home is threaded explicitly instead -- `load_koan_config(home)` / `save_koan_config(config, home)`, `FileKeyBackend(home)` / `get_key_backend(home)`, and a `ServerConfig.koan_home` field that the web layer reads to build the runs directory. The CLI resolves and validates the home once in `koan/__main__.py:main()` and hands it to both `cmd_run` and `cmd_memory`. An explicitly provided home must already exist or the CLI exits with an error (mirroring the `--add-dir` validation); the default `~/.koan` is exempt and still auto-creates on first use. The project-scoped memory directory `cwd/.koan/memory` is deliberately NOT affected -- it derives from the working directory, not the user home.

Rationale: full explicit threading was chosen to honor koan's standing rule against module-global singletons for runtime/config state. Rejected: keeping the path constants as module globals but making them settable once at startup (a smaller change, but it preserves exactly the ambient global the no-globals rule condemns); and a partial hybrid -- Leon explicitly chose the fully-threaded option. `KOAN_HOME` was added alongside the flag because it isolates two koan installs that would otherwise collide on a shared `~/.koan`, and it aids process-wide test isolation.

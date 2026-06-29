---
title: koan tests isolate from the developer's real ~/.koan via an autouse fixture
  that patches Path.home() to a temp dir; production code reads KOAN_HOME only in
  the CLI resolver, never in a dataclass default
type: decision
created: '2026-06-28T06:00:12Z'
modified: '2026-06-28T06:00:12Z'
related:
- 0253-koans-home-directory-is-configurable-via-home-and.md
- 0213-koan-forbids-module-global-singletons-for.md
---

koan's test suite is isolated from a developer's real `~/.koan` -- which holds `config.yaml`, the Fernet `master.key`, and `runs/` -- so no test reads or mutates it. Leon flagged this isolation as a hard requirement (tests must not affect a developer's actual configuration). The mechanism, adopted once the home directory became configurable: an autouse, function-scoped fixture in `tests/conftest.py` monkeypatches `Path.home()` to a per-test temp directory and returns the derived temp home. Because every home derivation bottoms out at `Path.home()` -- both the `resolve_koan_home` default branch and the `ServerConfig.koan_home` default (`field(default_factory=lambda: str(Path.home() / ".koan"))`) -- patching `Path.home()` redirects all of them, so even a programmatically constructed `AppState` that never sets `server.koan_home` lands in the temp dir. Tests that call the home-threaded functions directly (`load_koan_config`, `save_koan_config`, `FileKeyBackend`) pass the fixture's home explicitly. This replaced the prior idiom where individual test files monkeypatched the now-removed module globals (`koan.credentials.MASTER_KEY_PATH`, `koan.config.CONFIG_PATH`, `koan.web.app.RUNS_DIR`) at ad-hoc temp paths.

A competing design was drafted and then rejected: defaulting `ServerConfig.koan_home` to `field(default_factory=lambda: str(resolve_koan_home(None)))`, where `resolve_koan_home` reads the `KOAN_HOME` environment variable. Reading an environment variable inside a dataclass default is the implicit-ambient-read anti-pattern koan has repeatedly removed (the same reasoning behind deleting the credential env-shim and the `SEED_ENV_KEYS` gap-fill), so the `KOAN_HOME` read was confined to the single CLI resolver `resolve_koan_home`, invoked from `main()`. Also rejected: requiring every AppState-building test fixture to set `server.koan_home` explicitly, because a forgotten one falls through to the real home -- the precise failure the isolation must prevent -- whereas the `Path.home()` patch is a single net that cannot be forgotten per-test.

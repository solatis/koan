---
title: koan's argparse flags on the _common parent parser are reset to their default
  when passed before the subcommand unless default=argparse.SUPPRESS
type: lesson
created: '2026-06-28T06:00:02Z'
modified: '2026-06-28T06:00:02Z'
---

koan's CLI (`koan/__main__.py`) shares flags across subcommands by defining them on a `_common = argparse.ArgumentParser(add_help=False)` parent and passing `parents=[_common]` to both the top-level parser and each subparser (`run`, `memory`). With an ordinary default, a flag passed BEFORE the subcommand is silently discarded: `koan --home X run` resolves the value back to its default, while `koan run --home X` works. Root cause: the subparser inherits the same flag with the same `dest`, and argparse applies the subparser's default after parsing the top-level arguments, overwriting the value already captured at the top level. The long-standing `--debug` flag carried this latent bug -- `koan --debug run` did not enable debug logging -- and it stayed unnoticed because `--debug` was habitually passed after the subcommand.

Prevention: give such inherited flags `default=argparse.SUPPRESS`, so an unset flag leaves no attribute on the namespace and the subparser has nothing to overwrite; then read them with `getattr(args, "<name>", <fallback>)`. This was confirmed by parsing both argument orders against the real `_common` structure before adoption, and applied to both `--home` and `--debug`. The trap is that the after-subcommand position works, so testing only `koan run --flag X` passes while `koan --flag X run` silently regresses.

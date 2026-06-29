# koan/home.py -- pure koan home directory resolver.
#
# Resolution seam for the koan home directory.  Precedence:
#   --home flag (cli_home) > KOAN_HOME env var > Path.home() / ".koan"
#
# This module is dependency-light by design (stdlib only, no koan imports) so
# it can be imported early without triggering circular imports.  Validation --
# whether an explicitly provided home must exist -- is the CLI layer's job.

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def resolve_koan_home(
    cli_home: str | None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the koan home directory from the three-level precedence chain.

    Precedence: cli_home > env["KOAN_HOME"] > Path.home() / ".koan".

    The env parameter is injected for tests; pass None (the default) in
    production to read os.environ.  An explicit home is expanduser'd and
    resolve'd so a relative --home or a tilde path yields an absolute path
    consistent across the CLI and web layers.  The default branch returns
    the literal Path.home() / ".koan" unchanged, preserving today's behavior
    byte-for-byte when no override is set.

    This function never raises, never checks the filesystem, and never creates
    any directory.  Existence validation is the caller's responsibility.
    """
    env = os.environ if env is None else env
    explicit = cli_home if cli_home is not None else env.get("KOAN_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path.home() / ".koan"


def was_home_explicit(
    cli_home: str | None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when the home was explicitly set via --home or KOAN_HOME.

    Used by the CLI to decide whether to enforce the exist-and-is-directory
    check.  The default home (~/.koan) is exempt from that check so a first
    run on a clean machine works without pre-creating the directory.
    """
    env = os.environ if env is None else env
    return cli_home is not None or bool(env.get("KOAN_HOME"))

# CLI handler for `koan run` -- starts the Starlette/uvicorn server.
#
# In a development checkout (frontend/ directory exists next to the koan
# package), this module automatically rebuilds the Vite bundle into
# koan/web/static/app/ when frontend sources are newer than the last build.
# In an installed wheel the frontend/ directory is absent and the check is
# a no-op -- the pre-built assets ship inside the wheel.

from __future__ import annotations

import argparse
import asyncio
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn

from ..config import load_koan_config, save_koan_config
from ..credentials import CredentialStore, get_key_backend
from ..logger import get_logger
from ..state import AppState, hydrate_memory_projection
from ..web.app import FRONTEND_DIST, create_app

log = get_logger("cli.run")

# Resolve relative to the *repository root* (one level above the koan package).
# Only present in a development checkout -- absent in an installed wheel.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_SRC = _REPO_ROOT / "frontend" / "src"


def _frontend_needs_rebuild() -> bool:
    """True when frontend sources are newer than the last Vite build."""
    if not _FRONTEND_SRC.is_dir():
        return False  # not a dev checkout

    build_marker = FRONTEND_DIST / "index.html"
    if not build_marker.exists():
        return True  # never built

    build_mtime = build_marker.stat().st_mtime
    return any(
        p.stat().st_mtime > build_mtime
        for p in _FRONTEND_SRC.rglob("*")
        if p.is_file()
    )


def _rebuild_frontend() -> None:
    """Run ``npm run build`` in the frontend directory."""
    frontend_dir = _FRONTEND_SRC.parent
    log.info("Frontend sources changed -- rebuilding...")
    try:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        log.info("Frontend build complete.")
    except FileNotFoundError:
        log.warning("npm not found -- skipping frontend rebuild.")
    except subprocess.CalledProcessError as exc:
        log.error("Frontend build failed:\n%s", exc.stderr)
        sys.exit(1)


def _find_free_port(address: str) -> int:
    """Bind to port 0 on the given address; let the OS assign a free ephemeral port.

    Probes the actual bind address rather than loopback so that the port
    chosen is definitely free on the interface uvicorn will bind to.
    AF_INET6 is used iff the address is an IPv6 literal (contains ':').
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.bind((address, 0))
        return s.getsockname()[1]


def cmd_run(args: argparse.Namespace) -> None:
    """Start the koan web server. Expects args from the `koan run` subparser.

    Consumes args.koan_home (resolved and validated in main()) and records it
    on app_state.server.koan_home before any config or credential I/O.
    Resolves --add-dir paths into absolute strings stored on
    app_state.run.additional_dirs. Each path is validated as an existing
    directory; failures cause the process to exit with a clear message.
    """
    log_level = args.log_level

    if not args.skip_build and _frontend_needs_rebuild():
        _rebuild_frontend()

    address = args.address
    port = args.port if args.port is not None else _find_free_port(address)

    project_dir = Path.cwd()
    if not project_dir.is_dir():
        sys.exit(f"koan: project directory does not exist: {project_dir}")

    raw_extras = args.additional_dirs or []
    resolved_extras: list[str] = []
    for raw in raw_extras:
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            sys.exit(f"koan: --add-dir path does not exist or is not a directory: {raw}")
        resolved_extras.append(str(p))

    app_state = AppState()
    # Establish the resolved home on the server config before any I/O so the
    # web layer's _runs_dir() and all save handlers pick it up consistently.
    app_state.server.koan_home = str(args.koan_home)

    config = asyncio.run(load_koan_config(args.koan_home))
    app_state.provider_config.config = config

    # Initialize the credential store BEFORE any provider availability check
    # or memory operation. The store must be set on provider_config and as the
    # module-level active store so both web/agent paths and memory modules
    # resolve credentials without touching os.environ.
    # M1: env-seeding (seed_from_env) is removed (brief D13 -- credentials are
    # fully manual).  Only persist when stale envelopes were pruned at load.
    try:
        store = CredentialStore(config, get_key_backend(args.koan_home))
        if store.pruned:
            asyncio.run(save_koan_config(config, args.koan_home))
            log.info("credentials: persisted config after pruning stale envelopes")
        app_state.provider_config.credential_store = store
        # The module-global active store/config seams were removed; the live
        # credential store lives on app_state.provider_config and the per-run
        # frozen state is built at api_start_run via build_memory_models.
    except Exception as exc:
        log.error("credentials: store initialization failed -- providers will be unavailable: %s", exc)
    app_state.server.port = port
    app_state.server.address = address
    app_state.server.open_browser = not args.no_open
    app_state.server.initial_prompt = args.prompt
    app_state.server.yolo = args.yolo
    app_state.server.debug = getattr(args, "debug", False)
    if args.directed_phases:
        app_state.server.directed_phases = args.directed_phases
    app_state.run.project_dir = str(project_dir)
    app_state.run.additional_dirs = resolved_extras
    app_state.init_memory_services()
    hydrate_memory_projection(app_state)
    app = create_app(app_state)

    host = address
    log.info(
        "koan server starting: host=%s port=%d log_level=%s yolo=%s",
        host, port, log_level, args.yolo,
    )
    # timeout_graceful_shutdown=0: don't wait for HTTP clients to disconnect.
    # Agent cleanup happens in the lifespan shutdown handler instead.
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower(),
                timeout_graceful_shutdown=0)

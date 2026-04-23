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

from ..config import load_koan_config
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


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign a free ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cmd_run(args: argparse.Namespace) -> None:
    """Start the koan web server. Expects args from the `koan run` subparser."""
    log_level = args.log_level

    if not args.skip_build and _frontend_needs_rebuild():
        _rebuild_frontend()

    port = args.port if args.port is not None else _find_free_port()

    project_dir = Path.cwd()
    if not project_dir.is_dir():
        sys.exit(f"koan: project directory does not exist: {project_dir}")

    config = asyncio.run(load_koan_config())
    app_state = AppState()
    app_state.runner_config.config = config
    app_state.server.port = port
    app_state.server.open_browser = not args.no_open
    app_state.server.initial_prompt = args.prompt
    app_state.server.yolo = args.yolo
    app_state.server.debug = args.debug
    if args.directed_phases:
        app_state.server.directed_phases = args.directed_phases
    app_state.run.project_dir = str(project_dir)
    app_state.init_memory_services()
    hydrate_memory_projection(app_state)
    app = create_app(app_state)

    host = "127.0.0.1"
    log.info(
        "koan server starting: host=%s port=%d log_level=%s yolo=%s",
        host, port, log_level, args.yolo,
    )
    # timeout_graceful_shutdown=0: don't wait for HTTP clients to disconnect.
    # Agent cleanup happens in the lifespan shutdown handler instead.
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower(),
                timeout_graceful_shutdown=0)

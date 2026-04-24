# tests/evals/conftest.py
# Session-scoped pytest fixtures and helpers for koan eval tests.
#
# harvest_cache is a session-scoped dict keyed by (fixture_id, task_id, case_id).
# _get_harvest() checks the cache before calling run_koan(), ensuring each
# unique case runs the koan subprocess exactly once per pytest session regardless
# of how many test functions consume the result.
#
# asyncio.run() inside sync helpers is intentional: run_koan spins its own
# event loop and tears it down before returning. No pytest-asyncio plugin needed.

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

import pytest

from evals.cases import Case, CASES as _ALL_CASES, FIXTURES_DIR
from evals.runner import run_koan


log = logging.getLogger("koan.evals.conftest")

# Apply KOAN_EVAL_TASK filter -- env var makes test runs scope to a single
# task for iteration speed while keeping the full matrix available by default.
_EVAL_TASK_FILTER = os.environ.get("KOAN_EVAL_TASK")
CASES: list[Case] = (
    _ALL_CASES if not _EVAL_TASK_FILTER
    else [c for c in _ALL_CASES if _EVAL_TASK_FILTER in c.task_id]
)


def _case_id(case: Case) -> str:
    return f"{case.fixture_id}/{case.task_id}/{case.case_id}"


@pytest.fixture(scope="session", params=CASES, ids=[_case_id(c) for c in CASES])
def case(request) -> Case:
    return request.param


@pytest.fixture(scope="session")
def harvest_cache() -> dict[tuple, dict]:
    # Single mutable dict shared across the entire test session. Session scope
    # ensures run_koan() fires at most once per (fixture, task, case) triple.
    return {}


def _get_harvest(case: Case, cache: dict) -> dict:
    key = (case.fixture_id, case.task_id, case.case_id)
    if key not in cache:
        cid = _case_id(case)
        log.info("[%s] === HARVEST START ===", cid)
        try:
            h = asyncio.run(run_koan(case))
        except Exception:
            log.info("[%s] === HARVEST EXCEPTION ===", cid, exc_info=True)
            raise
        log.info(
            "[%s] === HARVEST DONE === phases=%s summaries=%d",
            cid,
            h.get("phase_order", []),
            len(h.get("phase_summaries", {})),
        )
        cache[key] = h
        _dump_harvest(case, h)
    return cache[key]


def _dump_harvest(case: Case, h: dict) -> None:
    dump_dir = FIXTURES_DIR.parent / "harvest_dumps"
    dump_dir.mkdir(exist_ok=True)
    slug = f"{case.fixture_id}__{case.task_id}__{case.case_id}"
    (dump_dir / f"{slug}.json").write_text(
        json.dumps(h, indent=2, default=str), encoding="utf-8",
    )


# -- Hyperparameter detection --------------------------------------------------

def _detect_orchestrator_model() -> str:
    # Fail-soft: any exception returns "unknown" so the test session still runs
    # on fresh installs or in CI environments with a different config path.
    try:
        from koan.config import load_koan_config
        from koan.runners.registry import RunnerRegistry
        config = asyncio.run(load_koan_config())
        registry = RunnerRegistry()
        # SubagentRole is a Literal type alias, not an enum; pass the string directly.
        _, model, _ = registry.resolve_agent_config("orchestrator", config)
        return model
    except Exception:
        return os.environ.get("KOAN_ORCHESTRATOR_MODEL", "unknown")


def _detect_koan_git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(FIXTURES_DIR.parent.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


_ORCH_MODEL = _detect_orchestrator_model()
_JUDGE_MODEL = "gemini-3-pro-preview"
_KOAN_GIT_SHA = _detect_koan_git_sha()


# Module-level dict consumed by @deepeval.log_hyperparameters in test_koan.py.
# Under `deepeval test run`, the shared test_run is already created at
# pytest_sessionstart, so the decorator attaches correctly at module import time.
HYPERPARAMETERS: dict[str, str] = {
    "orchestrator_model": _ORCH_MODEL,
    "judge_model":        _JUDGE_MODEL,
    "koan_git_sha":       _KOAN_GIT_SHA,
}

# tests/evals/conftest.py
# Session-scoped pytest fixtures for koan eval tests.
#
# The `case` fixture is parametrized over all discovered cases, so pytest
# instantiates one harvest per unique case for the session. All nine
# per-section test functions that depend on `harvest` for a given case
# reuse pytest's cached result -- koan runs exactly once per case.
#
# asyncio.run() inside a sync fixture is intentional: run_koan spins its
# own uvicorn event loop and tears it down before returning, so there is
# no residual loop state that could conflict with pytest-asyncio. No
# pytest-asyncio plugin is needed.

import asyncio
from pathlib import Path

import pytest

from evals.cases import Case, discover_cases
from evals.runner import run_koan


FIXTURES_DIR = Path(__file__).resolve().parents[2] / "evals" / "fixtures"

CASES: list[Case] = discover_cases(FIXTURES_DIR)


def _case_id(case: Case) -> str:
    return f"{case.fixture_id}/{case.task_id}/{case.case_id}"


@pytest.fixture(scope="session", params=CASES, ids=[_case_id(c) for c in CASES])
def case(request) -> Case:
    return request.param


@pytest.fixture(scope="session")
def harvest(case: Case) -> dict:
    # pytest keys the fixture cache on the `case` parameter automatically;
    # there is exactly one harvest instance per case param for the session.
    return asyncio.run(run_koan(case))

from __future__ import annotations

import pytest

from services.planner.app import main as planner_main


@pytest.fixture(autouse=True)
def _reset_planner_bootstrap_singleton() -> None:
    """Force a fresh ``PlannerBootstrap`` for every test.

    ``services.planner.app.main._planner_bootstrap()`` lazily builds a
    module-level singleton from ``os.environ`` the first time it's called,
    then caches it for the rest of the process. In production that's exactly
    right (one process, fixed env vars). In a pytest session, tests across
    different files run in a single process — whichever test calls it first
    (e.g. ``test_planner.py::test_rule_based_plan_schema``, which never sets
    ``SCHEMA_REGISTRY_PATH``) bakes its env into the singleton for every test
    that follows, silently ignoring any ``monkeypatch.setenv`` a later test
    performs. Resetting the singleton before each test makes
    ``_planner_bootstrap()`` re-read the environment every time, so each
    test's own env changes actually take effect.
    """

    planner_main._PLANNER_BOOTSTRAP = None
    planner_main._PLANNER_CACHE_SESSION_STORE = None

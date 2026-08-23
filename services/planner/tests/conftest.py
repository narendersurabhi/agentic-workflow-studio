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


@pytest.fixture(autouse=True)
def _default_capability_mode_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Match the deployed default for ``CAPABILITY_MODE``.

    ``docker-compose.yml`` and ``deploy/k8s/configmap.yaml`` both default
    ``CAPABILITY_MODE`` to ``"enabled"`` for every service. But
    ``libs.core.capability_registry.resolve_capability_mode()`` falls back to
    ``"disabled"`` when the env var is simply absent -- which is exactly the
    case for a bare ``pytest`` run that never sources compose/k8s env files.
    Several planner tests build plans that reference capability-style
    (dotted, e.g. ``document.docx.render``) request IDs without setting
    ``CAPABILITY_MODE`` themselves, implicitly assuming the deployed default.
    Under the code-level "disabled" fallback, ``_planner_capabilities()``
    returns an empty dict, so those dotted IDs never get canonicalized to
    their tool names and validation fails with ``unknown_tool_or_capability``.
    Setting the deployed default here closes that gap; any test that needs
    "disabled" (or another mode) still overrides it locally via its own
    ``monkeypatch.setenv``/``delenv``, which takes precedence over this
    fixture since it runs during the test body, after this fixture's setup.
    """

    monkeypatch.setenv("CAPABILITY_MODE", "enabled")

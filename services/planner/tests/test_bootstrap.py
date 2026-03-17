from __future__ import annotations

from services.planner.app import bootstrap, runtime_service


def test_build_bootstrap_from_env_parses_service_and_runtime_config() -> None:
    captured: list[runtime_service.PlannerRuntimeConfig] = []

    planner_bootstrap = bootstrap.build_bootstrap_from_env(
        {
            "REDIS_URL": "redis://example:6379/1",
            "PLANNER_MODE": "llm",
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-5-mini",
            "OPENAI_BASE_URL": "https://api.example.com",
            "OPENAI_TEMPERATURE": "0.2",
            "OPENAI_MAX_OUTPUT_TOKENS": "400",
            "PLANNER_MAX_DEPTH": "3",
            "OPENAI_TIMEOUT_S": "11.5",
            "OPENAI_MAX_RETRIES": "2",
            "SCHEMA_REGISTRY_PATH": "/tmp/schemas",
            "PLANNER_METRICS_PORT": "9201",
        },
        redis_client_factory=lambda config: captured.append(config) or object(),
    )

    assert planner_bootstrap.service_config.mode == "llm"
    assert planner_bootstrap.service_config.max_dependency_depth == 3
    assert planner_bootstrap.service_config.schema_registry_path == "/tmp/schemas"
    assert planner_bootstrap.runtime_config.redis_url == "redis://example:6379/1"
    assert planner_bootstrap.runtime_config.metrics_port == 9201
    assert planner_bootstrap.runtime_config.openai_temperature == 0.2
    assert planner_bootstrap.runtime_config.openai_timeout_s == 11.5
    assert planner_bootstrap.runtime_config.openai_max_retries == 2
    assert captured and captured[0] is planner_bootstrap.runtime_config


def test_planner_bootstrap_starts_metrics_only_once() -> None:
    planner_bootstrap = bootstrap.PlannerBootstrap(
        service_config=bootstrap.planner_service.PlannerServiceConfig(),
        runtime_config=runtime_service.PlannerRuntimeConfig(
            redis_url="redis://redis:6379/0",
            metrics_port=9101,
        ),
        redis_client=object(),
    )
    calls: list[int] = []

    planner_bootstrap.ensure_metrics_started(calls.append)
    planner_bootstrap.ensure_metrics_started(calls.append)

    assert calls == [9101]

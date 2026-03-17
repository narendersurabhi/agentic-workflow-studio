from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable

from services.planner.app import planner_service, runtime_service


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass
class PlannerBootstrap:
    service_config: planner_service.PlannerServiceConfig
    runtime_config: runtime_service.PlannerRuntimeConfig
    redis_client: object
    _metrics_started: bool = False

    def ensure_metrics_started(self, start_metrics_server: Callable[[int], None]) -> None:
        if self._metrics_started:
            return
        start_metrics_server(self.runtime_config.metrics_port)
        self._metrics_started = True


def build_bootstrap_from_env(
    env: Mapping[str, str],
    *,
    redis_client_factory: Callable[[runtime_service.PlannerRuntimeConfig], object],
) -> PlannerBootstrap:
    redis_url = env.get("REDIS_URL", "redis://redis:6379/0")
    planner_mode = env.get("PLANNER_MODE", "rule_based")
    llm_provider_name = env.get("LLM_PROVIDER", "mock")
    openai_api_key = env.get("OPENAI_API_KEY", "")
    openai_model = env.get("OPENAI_MODEL", "")
    openai_base_url = env.get("OPENAI_BASE_URL", "https://api.openai.com")
    openai_temperature = parse_optional_float(env.get("OPENAI_TEMPERATURE"))
    openai_max_output_tokens = parse_optional_int(env.get("OPENAI_MAX_OUTPUT_TOKENS"))
    max_dependency_depth = parse_optional_int(env.get("PLANNER_MAX_DEPTH"))
    openai_timeout_s = parse_optional_float(env.get("OPENAI_TIMEOUT_S"))
    openai_max_retries = parse_optional_int(env.get("OPENAI_MAX_RETRIES"))
    schema_registry_path = env.get("SCHEMA_REGISTRY_PATH", "/app/schemas")
    metrics_port = parse_optional_int(env.get("PLANNER_METRICS_PORT")) or 9101

    service_config = planner_service.PlannerServiceConfig(
        mode=planner_mode,
        max_dependency_depth=max_dependency_depth,
        semantic_hint_limit=10,
        schema_registry_path=schema_registry_path,
    )
    runtime_config = runtime_service.PlannerRuntimeConfig(
        redis_url=redis_url,
        metrics_port=metrics_port,
        planner_mode=planner_mode,
        llm_provider_name=llm_provider_name,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_base_url=openai_base_url,
        openai_temperature=openai_temperature,
        openai_max_output_tokens=openai_max_output_tokens,
        openai_timeout_s=openai_timeout_s,
        openai_max_retries=openai_max_retries,
    )
    return PlannerBootstrap(
        service_config=service_config,
        runtime_config=runtime_config,
        redis_client=redis_client_factory(runtime_config),
    )

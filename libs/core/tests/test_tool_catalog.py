import pytest

from libs.core import tool_registry
from libs.framework.tool_runtime import ToolRegistry


def test_register_default_tools_adds_builtin_specs() -> None:
    registry = ToolRegistry()

    tool_registry.register_default_tools(
        registry,
        handlers=tool_registry._default_catalog_handlers(),
        http_fetch_enabled=False,
        llm_enabled=False,
        llm_provider=None,
    )

    specs = {spec.name for spec in registry.list_specs()}
    assert "math_eval" in specs
    assert "docx_render_from_spec" in specs
    assert "file_write_text" in specs


def test_register_default_tools_adds_llm_tool_when_enabled(mocker) -> None:
    registry = ToolRegistry()
    mock_provider = mocker.MagicMock()

    tool_registry.register_default_tools(
        registry,
        handlers=tool_registry._default_catalog_handlers(),
        http_fetch_enabled=False,
        llm_enabled=True,
        llm_provider=mock_provider,
    )

    specs = {spec.name for spec in registry.list_specs()}
    assert "llm_generate" in specs


def test_register_default_tools_requires_provider_when_llm_enabled() -> None:
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="llm_enabled requires a llm_provider instance"):
        tool_registry.register_default_tools(
            registry,
            handlers=tool_registry._default_catalog_handlers(),
            http_fetch_enabled=False,
            llm_enabled=True,
            llm_provider=None,
        )

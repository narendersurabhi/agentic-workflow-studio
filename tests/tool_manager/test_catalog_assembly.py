import pytest

from libs.framework.tool_runtime import ToolRegistry
from libs.tool_manager import registry as tool_registry


def test_register_default_tools_adds_builtin_specs() -> None:
    registry = ToolRegistry()

    tool_registry.register_default_tools(
        registry,
        handlers=tool_registry._default_catalog_handlers(),
        llm_enabled=False,
        llm_provider=None,
    )

    specs = {spec.name for spec in registry.list_specs()}
    assert "search_text" in specs
    assert "docx_render_from_spec" in specs
    assert "file_write_text" in specs


def test_register_default_tools_adds_llm_tool_when_enabled(mocker) -> None:
    registry = ToolRegistry()
    mock_provider = mocker.MagicMock()

    tool_registry.register_default_tools(
        registry,
        handlers=tool_registry._default_catalog_handlers(),
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
            llm_enabled=True,
            llm_provider=None,
        )

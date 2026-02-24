from datetime import datetime
import json
from pathlib import Path

import pytest

from libs.core import models
from services.planner.app.main import _ensure_renderer_output_extensions, _validate_plan


@pytest.fixture(autouse=True)
def _disable_governance(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_GOVERNANCE_ENABLED", "false")


def _job() -> models.Job:
    now = datetime.utcnow()
    return models.Job(
        id="job-1",
        goal="test",
        context_json={"today": "2026-02-21", "topic": "distributed systems"},
        status=models.JobStatus.queued,
        created_at=now,
        updated_at=now,
        priority=0,
        metadata={},
    )


def _plan_with_task(
    tool_name: str, tool_input: dict, deps: list[str] | None = None
) -> models.PlanCreate:
    return models.PlanCreate(
        planner_version="1",
        tasks_summary="test",
        dag_edges=[],
        tasks=[
            models.TaskCreate(
                name="task-1",
                description="desc",
                instruction="instr",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="schemas/test",
                deps=deps or [],
                tool_requests=[tool_name],
                tool_inputs={tool_name: tool_input},
                critic_required=False,
            )
        ],
    )


def _tool(
    name: str, input_schema: dict, *, memory_reads: list[str] | None = None
) -> models.ToolSpec:
    return models.ToolSpec(
        name=name,
        description="test tool",
        input_schema=input_schema,
        output_schema={"type": "object"},
        memory_reads=memory_reads or [],
    )


def test_validate_plan_rejects_missing_root_required_with_anyof() -> None:
    plan = _plan_with_task("combo_tool", {"a": "value"})
    tool = _tool(
        "combo_tool",
        {
            "type": "object",
            "properties": {
                "base": {"type": "string"},
                "a": {"type": "string"},
                "b": {"type": "string"},
            },
            "required": ["base"],
            "anyOf": [{"required": ["a"]}, {"required": ["b"]}],
        },
    )
    valid, reason = _validate_plan(plan, [tool], _job())
    assert not valid
    assert reason.startswith("tool_inputs_invalid:combo_tool:task-1")


def test_validate_plan_enforces_nested_allof_contracts() -> None:
    plan = _plan_with_task("nested_tool", {})
    tool = _tool(
        "nested_tool",
        {
            "type": "object",
            "properties": {"target_role_name": {"type": "string", "minLength": 1}},
            "allOf": [{"required": ["target_role_name"]}],
        },
    )
    valid, reason = _validate_plan(plan, [tool], _job())
    assert not valid
    assert reason.startswith("tool_inputs_invalid:nested_tool:task-1")


def test_validate_plan_allows_dependency_filled_inputs() -> None:
    plan = _plan_with_task("improve_spec", {}, deps=["generate_spec"])
    tool = _tool(
        "improve_spec",
        {
            "type": "object",
            "properties": {
                "document_spec": {"type": "object"},
                "validation_report": {"type": "object"},
            },
            "required": ["document_spec", "validation_report"],
        },
    )
    valid, reason = _validate_plan(plan, [tool], _job())
    assert valid, reason


def test_validate_plan_allows_reference_object_inputs() -> None:
    plan = _plan_with_task(
        "docx_generate_from_spec",
        {
            "path": "documents/out.docx",
            "document_spec": {
                "$from": "dependencies_by_name.generate_spec.llm_generate_document_spec.document_spec"
            },
        },
        deps=["generate_spec"],
    )
    tool = _tool(
        "docx_generate_from_spec",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "document_spec": {"type": "object"},
            },
            "required": ["path", "document_spec"],
        },
    )
    valid, reason = _validate_plan(plan, [tool], _job())
    assert valid, reason


def test_validate_plan_rejects_docx_render_without_output_path() -> None:
    plan = _plan_with_task("docx_render_like", {}, deps=["generate_data"])
    tool = _tool(
        "docx_render_like",
        {
            "type": "object",
            "properties": {
                "data": {"type": "object"},
                "template_id": {"type": "string"},
                "template_path": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "required": ["data", "output_path"],
            "anyOf": [{"required": ["template_id"]}, {"required": ["template_path"]}],
        },
    )
    valid, reason = _validate_plan(plan, [tool], _job())
    assert not valid
    assert reason.startswith("tool_inputs_invalid:docx_render_like:task-1")


def test_validate_plan_accepts_memory_backed_contract_branch() -> None:
    plan = _plan_with_task("derive_output_filename", {})
    tool = _tool(
        "derive_output_filename",
        {
            "type": "object",
            "properties": {"topic": {"type": "string"}, "memory": {"type": "object"}},
            "allOf": [{"anyOf": [{"required": ["topic"]}, {"required": ["memory"]}]}],
        },
        memory_reads=["job_context", "task_outputs"],
    )
    valid, reason = _validate_plan(plan, [tool], _job())
    assert valid, reason


def test_validate_plan_accepts_enabled_capability_with_valid_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    schema_path = tmp_path / "capability_input.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        ),
        encoding="utf-8",
    )
    capability_registry_path = tmp_path / "capability_registry.json"
    capability_registry_path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {
                        "id": "github.repo.list",
                        "description": "List repos",
                        "enabled": True,
                        "input_schema_ref": str(schema_path),
                        "adapters": [
                            {
                                "type": "mcp",
                                "server_id": "github_remote",
                                "tool_name": "github_repo_list",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPABILITY_MODE", "enabled")
    monkeypatch.setenv("CAPABILITY_REGISTRY_PATH", str(capability_registry_path))
    plan = _plan_with_task("github.repo.list", {"query": "agentic"})
    valid, reason = _validate_plan(plan, [], _job())
    assert valid, reason


def test_validate_plan_rejects_capability_with_missing_required_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    schema_path = tmp_path / "capability_input.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        ),
        encoding="utf-8",
    )
    capability_registry_path = tmp_path / "capability_registry.json"
    capability_registry_path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {
                        "id": "github.repo.list",
                        "description": "List repos",
                        "enabled": True,
                        "input_schema_ref": str(schema_path),
                        "adapters": [
                            {
                                "type": "mcp",
                                "server_id": "github_remote",
                                "tool_name": "github_repo_list",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPABILITY_MODE", "enabled")
    monkeypatch.setenv("CAPABILITY_REGISTRY_PATH", str(capability_registry_path))
    plan = _plan_with_task("github.repo.list", {})
    valid, reason = _validate_plan(plan, [], _job())
    assert not valid
    assert reason.startswith("capability_inputs_invalid:github.repo.list:task-1:")


def test_ensure_renderer_output_extensions_sets_pdf_on_derive_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capability_registry_path = tmp_path / "capability_registry.json"
    capability_registry_path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {
                        "id": "document.output.derive",
                        "description": "derive output path",
                        "enabled": True,
                        "planner_hints": {"derives_output_path": True},
                        "adapters": [
                            {
                                "type": "tool",
                                "server_id": "local_worker",
                                "tool_name": "derive_output_filename",
                            }
                        ],
                    },
                    {
                        "id": "document.pdf.generate",
                        "description": "render pdf",
                        "enabled": True,
                        "planner_hints": {"required_output_extension": "pdf"},
                        "adapters": [
                            {
                                "type": "tool",
                                "server_id": "local_worker",
                                "tool_name": "pdf_generate_from_spec",
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPABILITY_MODE", "enabled")
    monkeypatch.setenv("CAPABILITY_REGISTRY_PATH", str(capability_registry_path))
    plan = models.PlanCreate(
        planner_version="1",
        tasks_summary="doc pipeline",
        dag_edges=[],
        tasks=[
            models.TaskCreate(
                name="GenerateSpec",
                description="gen",
                instruction="gen",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="schemas/DocumentSpec",
                deps=[],
                tool_requests=["document.spec.generate"],
                tool_inputs={"document.spec.generate": {"job": {}}},
                critic_required=False,
            ),
            models.TaskCreate(
                name="DeriveOutputPath",
                description="derive",
                instruction="derive",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="schemas/docx_path",
                deps=["GenerateSpec"],
                tool_requests=["document.output.derive"],
                tool_inputs={
                    "document.output.derive": {
                        "topic": "Latency",
                        "today": "2026-02-24",
                        "output_dir": "documents",
                        "document_type": "document",
                    }
                },
                critic_required=False,
            ),
            models.TaskCreate(
                name="RenderPdf",
                description="render",
                instruction="render",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="schemas/pdf_output",
                deps=["GenerateSpec", "DeriveOutputPath"],
                tool_requests=["document.pdf.generate"],
                tool_inputs={
                    "document.pdf.generate": {
                        "document_spec": {
                            "$from": [
                                "dependencies_by_name",
                                "GenerateSpec",
                                "document.spec.generate",
                                "document_spec",
                            ]
                        },
                        "path": {
                            "$from": [
                                "dependencies_by_name",
                                "DeriveOutputPath",
                                "document.output.derive",
                                "path",
                            ]
                        },
                    }
                },
                critic_required=False,
            ),
        ],
    )
    updated = _ensure_renderer_output_extensions(plan)
    derive_inputs = updated.tasks[1].tool_inputs["document.output.derive"]
    assert derive_inputs["output_extension"] == "pdf"


def test_ensure_renderer_output_extensions_keeps_explicit_extension_when_aligned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capability_registry_path = tmp_path / "capability_registry.json"
    capability_registry_path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {
                        "id": "document.output.derive",
                        "description": "derive output path",
                        "enabled": True,
                        "planner_hints": {"derives_output_path": True},
                        "adapters": [
                            {
                                "type": "tool",
                                "server_id": "local_worker",
                                "tool_name": "derive_output_filename",
                            }
                        ],
                    },
                    {
                        "id": "document.pdf.generate",
                        "description": "render pdf",
                        "enabled": True,
                        "planner_hints": {"required_output_extension": "pdf"},
                        "adapters": [
                            {
                                "type": "tool",
                                "server_id": "local_worker",
                                "tool_name": "pdf_generate_from_spec",
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAPABILITY_MODE", "enabled")
    monkeypatch.setenv("CAPABILITY_REGISTRY_PATH", str(capability_registry_path))
    plan = models.PlanCreate(
        planner_version="1",
        tasks_summary="doc pipeline",
        dag_edges=[],
        tasks=[
            models.TaskCreate(
                name="DeriveOutputPath",
                description="derive",
                instruction="derive",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="schemas/docx_path",
                deps=[],
                tool_requests=["document.output.derive"],
                tool_inputs={
                    "document.output.derive": {
                        "topic": "Latency",
                        "today": "2026-02-24",
                        "output_dir": "documents",
                        "document_type": "document",
                        "output_extension": "pdf",
                    }
                },
                critic_required=False,
            ),
            models.TaskCreate(
                name="RenderPdf",
                description="render",
                instruction="render",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="schemas/pdf_output",
                deps=["DeriveOutputPath"],
                tool_requests=["document.pdf.generate"],
                tool_inputs={
                    "document.pdf.generate": {
                        "path": {
                            "$from": [
                                "dependencies_by_name",
                                "DeriveOutputPath",
                                "document.output.derive",
                                "path",
                            ]
                        }
                    }
                },
                critic_required=False,
            ),
        ],
    )
    updated = _ensure_renderer_output_extensions(plan)
    derive_inputs = updated.tasks[0].tool_inputs["document.output.derive"]
    assert derive_inputs["output_extension"] == "pdf"

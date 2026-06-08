"""Unit tests for agent.run self-identification and spawned-agent reporting."""

from __future__ import annotations

from libs.core.llm_provider import LLMRequest, LLMResponse
from libs.tools import agent_tools


class _StubProvider:
    """Minimal LLMProvider stub (no .client → uses the text-ReAct path)."""

    def __init__(self, content: str) -> None:
        self._content = content

    def generate_request(self, request: LLMRequest) -> LLMResponse:  # noqa: ARG002
        return LLMResponse(content=self._content)


def test_agent_run_reports_self_descriptor() -> None:
    provider = _StubProvider('{"thought": "done", "final_answer": "ok"}')
    result = agent_tools.agent_run(
        {"goal": "do a thing", "role": "researcher"},
        provider,
        invoke_capability=lambda cap_id, args: {},
    )
    agents = result["agents"]
    assert len(agents) == 1
    self_descriptor = agents[0]
    assert self_descriptor["agent_id"].startswith("agent-run-d0")
    assert self_descriptor["role"] == "researcher"
    assert self_descriptor["depth"] == 0
    assert self_descriptor["status"] == "done"


def test_agent_run_honours_explicit_agent_id() -> None:
    provider = _StubProvider('{"final_answer": "ok"}')
    result = agent_tools.agent_run(
        {"goal": "x", "agent_id": "lead-agent"},
        provider,
        invoke_capability=lambda cap_id, args: {},
    )
    assert result["agents"][0]["agent_id"] == "lead-agent"


def test_resolve_input_schema_finds_real_schema_regardless_of_cwd(tmp_path, monkeypatch) -> None:
    # Even when CWD has no schemas/ dir (as in the worker container), the
    # resolver locates the schema relative to the module / repo root.
    monkeypatch.chdir(tmp_path)

    class _Spec:
        input_schema_ref = "agent_capability_input"
        capability_id = "agent.run"

    schema = agent_tools._resolve_input_schema(_Spec())
    assert schema.get("type") == "object"
    assert "goal" in schema.get("properties", {})
    assert "allowed_capability_ids" in schema.get("properties", {})


def test_accumulate_spawned_agents_bubbles_only_agent_run_children() -> None:
    spawned: list[dict] = []
    # A sub-agent.run call contributes its reported agent tree.
    agent_tools._accumulate_spawned_agents(
        spawned,
        "agent.run",
        {"agents": [{"agent_id": "child-1"}, {"agent_id": "child-2"}]},
    )
    assert [a["agent_id"] for a in spawned] == ["child-1", "child-2"]

    # A non-agent capability returning an "agents" key is ignored.
    agent_tools._accumulate_spawned_agents(
        spawned,
        "filesystem.workspace.list",
        {"agents": [{"agent_id": "not-an-agent"}]},
    )
    assert [a["agent_id"] for a in spawned] == ["child-1", "child-2"]

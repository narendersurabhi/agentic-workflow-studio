from libs.tools import coder_tools
from pathlib import Path


def test_coding_agent_publish_pr_normalizes_same_branch_as_base(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello", encoding="utf-8")

    def safe_workspace_path(workspace_path: str, relative_path: str) -> Path:
        del relative_path
        assert workspace_path == "workspace"
        return workspace

    def invoke_capability(name: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((name, payload))
        return {"ok": True}

    out = coder_tools.coding_agent_publish_pr(
        {
            "owner": "narendersurabhi",
            "repo": "scientific-agent-lab",
            "branch": "main",
            "base": "main",
            "workspace_path": "workspace",
            "include_globs": ["README.md"],
        },
        safe_workspace_path=safe_workspace_path,
        invoke_capability=invoke_capability,
    )

    expected_branch = "codex/scientific-agent-lab"
    assert out["branch"] == expected_branch
    assert out["base"] == "main"
    assert calls[0] == (
        "github.branch.create",
        {
            "owner": "narendersurabhi",
            "repo": "scientific-agent-lab",
            "branch": expected_branch,
            "from_branch": "main",
        },
    )
    assert calls[1][0] == "github.files.push"
    assert calls[1][1]["branch"] == expected_branch
    assert calls[2][0] == "github.pull_request.create"
    assert calls[2][1]["head"] == expected_branch
    assert calls[2][1]["base"] == "main"

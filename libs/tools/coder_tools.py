from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from libs.framework.tool_runtime import ToolExecutionError


def _as_str_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out or list(default)


def _matches_any(path: str, patterns: list[str]) -> bool:
    pure = PurePosixPath(path)
    for pattern in patterns:
        if pure.match(pattern) or fnmatch.fnmatch(path, pattern):
            return True
    return False


def _collect_workspace_files_for_push(
    root: Path,
    *,
    include_globs: list[str],
    exclude_globs: list[str],
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    files: list[dict[str, str]] = []
    skipped: dict[str, list[str]] = {
        "excluded": [],
        "too_large": [],
        "non_utf8": [],
    }
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _matches_any(rel, exclude_globs):
            skipped["excluded"].append(rel)
            continue
        if include_globs and not _matches_any(rel, include_globs):
            skipped["excluded"].append(rel)
            continue
        file_bytes = path.stat().st_size
        if file_bytes > max_file_bytes:
            skipped["too_large"].append(rel)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped["non_utf8"].append(rel)
            continue
        encoded_len = len(content.encode("utf-8"))
        if total_bytes + encoded_len > max_total_bytes:
            break
        files.append({"path": rel, "content": content})
        total_bytes += encoded_len
        if len(files) >= max_files:
            break
    return files, skipped


def _default_pr_branch_name(repo: str) -> str:
    repo_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repo.strip()).strip(".-")
    if not repo_slug:
        repo_slug = "workspace"
    return f"codex/{repo_slug}"


def coding_agent_publish_pr(
    payload: dict[str, Any],
    *,
    safe_workspace_path: Callable[[str, str], Path],
    invoke_capability: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    owner = payload.get("owner")
    repo = payload.get("repo")
    branch = payload.get("branch")
    base = payload.get("base", "main")
    workspace_path = payload.get("workspace_path")
    if not isinstance(owner, str) or not owner.strip():
        raise ToolExecutionError("Missing owner")
    if not isinstance(repo, str) or not repo.strip():
        raise ToolExecutionError("Missing repo")
    if not isinstance(branch, str) or not branch.strip():
        raise ToolExecutionError("Missing branch")
    if not isinstance(base, str) or not base.strip():
        raise ToolExecutionError("Missing base")
    if not isinstance(workspace_path, str) or not workspace_path.strip():
        raise ToolExecutionError("Missing workspace_path")
    branch = branch.strip()
    base = base.strip()
    if branch == base:
        branch = _default_pr_branch_name(repo)

    include_globs = _as_str_list(payload.get("include_globs"), ["**/*"])
    exclude_globs = _as_str_list(
        payload.get("exclude_globs"),
        [".git/**", "**/.git/**", "IMPLEMENTATION_PLAN.md"],
    )
    max_files = payload.get("max_files", 200)
    if not isinstance(max_files, int) or max_files < 1:
        max_files = 200
    max_file_bytes = payload.get("max_file_bytes", 200_000)
    if not isinstance(max_file_bytes, int) or max_file_bytes < 1:
        max_file_bytes = 200_000
    max_total_bytes = payload.get("max_total_bytes", 2_000_000)
    if not isinstance(max_total_bytes, int) or max_total_bytes < 1:
        max_total_bytes = 2_000_000

    root = safe_workspace_path(workspace_path, "")
    if not root.exists() or not root.is_dir():
        raise ToolExecutionError("workspace_path not found or not a directory")

    files, skipped = _collect_workspace_files_for_push(
        root,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    if not files:
        raise ToolExecutionError("No files selected for push")

    branch_create_result: dict[str, Any] = {}
    try:
        branch_create_result = invoke_capability(
            "github.branch.create",
            {"owner": owner, "repo": repo, "branch": branch, "from_branch": base},
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if (
            "already exists" not in message
            and "reference already exists" not in message
            and "name already exists" not in message
        ):
            raise
        branch_create_result = {"status": "exists"}

    commit_message = payload.get("message")
    if not isinstance(commit_message, str) or not commit_message.strip():
        commit_message = f"chore(codegen): apply autonomous changes for {branch}"

    push_result = invoke_capability(
        "github.files.push",
        {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "files": files,
            "message": commit_message,
        },
    )

    pr_title = payload.get("title")
    if not isinstance(pr_title, str) or not pr_title.strip():
        pr_title = f"[codegen] {branch}"
    pr_body = payload.get("body")
    if not isinstance(pr_body, str):
        pr_body = (
            "Automated PR created by codegen.publish_pr.\n\n"
            f"- Branch: `{branch}`\n"
            f"- Base: `{base}`\n"
            f"- Files pushed: {len(files)}"
        )
    pr_head = payload.get("head")
    if not isinstance(pr_head, str) or not pr_head.strip():
        pr_head = branch

    pr_payload: dict[str, Any] = {
        "owner": owner,
        "repo": repo,
        "title": pr_title,
        "head": pr_head,
        "base": base,
        "body": pr_body,
    }
    if isinstance(payload.get("draft"), bool):
        pr_payload["draft"] = payload.get("draft")
    if isinstance(payload.get("maintainer_can_modify"), bool):
        pr_payload["maintainer_can_modify"] = payload.get("maintainer_can_modify")
    pr_result = invoke_capability("github.pull_request.create", pr_payload)

    return {
        "branch": branch,
        "base": base,
        "selected_files": len(files),
        "selected_paths_preview": [entry["path"] for entry in files[:20]],
        "skipped": skipped,
        "branch_create": branch_create_result,
        "push_result": push_result,
        "pull_request": pr_result,
    }

"""Git worktree helpers for agent workspace isolation.

A worktree gives an agent its own checked-out branch in a temporary directory.
On failure the worktree is force-removed, leaving the parent repo clean.
On success the worktree branch stays in place for the caller to inspect/merge.
"""
from __future__ import annotations

import logging
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from libs.framework.tool_runtime import ToolExecutionError

LOGGER = logging.getLogger(__name__)


def create_worktree(
    repo_path: Path | str,
    branch: str,
    *,
    base: str = "HEAD",
    worktree_parent: Path | str | None = None,
) -> Path:
    """Create a linked worktree for *branch* at a path derived from the branch name.

    Args:
        repo_path: path to the git repository root
        branch: name of the new branch to create in the worktree
        base: commit-ish to branch from (default HEAD)
        worktree_parent: directory to create the worktree inside;
                         defaults to a sibling of repo_path
    """
    repo = Path(repo_path).resolve()
    parent = Path(worktree_parent).resolve() if worktree_parent else repo.parent
    safe_name = branch.replace("/", "-").replace(".", "-")
    worktree_path = parent / f".wt-{safe_name}"

    try:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", branch, base],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ToolExecutionError(
            f"git worktree add failed for branch '{branch}': {exc.stderr.strip()}"
        ) from exc

    LOGGER.info("worktree: created branch=%s path=%s", branch, worktree_path)
    return worktree_path


def remove_worktree(worktree_path: Path | str, *, force: bool = False) -> None:
    """Remove a linked worktree. Logs but does not raise on failure."""
    path = Path(worktree_path).resolve()
    cmd = ["git", "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(path))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        LOGGER.warning(
            "worktree: remove failed path=%s force=%s stderr=%s",
            path,
            force,
            result.stderr.strip(),
        )
    else:
        LOGGER.info("worktree: removed path=%s", path)


@contextmanager
def worktree_context(
    repo_path: Path | str,
    *,
    branch_prefix: str = "agent",
    base: str = "HEAD",
    worktree_parent: Path | str | None = None,
) -> Generator[Path, None, None]:
    """Context manager that creates a git worktree on enter and cleans up on exit.

    On a clean exit: the worktree branch is left intact so the caller can
    inspect or merge it. On any exception: the worktree is force-removed so
    no dirty state accumulates in the repo.

    Yields:
        Path to the worktree root (use as workspace_path for agent tool calls).
    """
    branch = f"{branch_prefix}-{uuid.uuid4().hex[:8]}"
    worktree_path: Path | None = None
    try:
        worktree_path = create_worktree(
            repo_path,
            branch,
            base=base,
            worktree_parent=worktree_parent,
        )
        yield worktree_path
    except Exception:
        if worktree_path is not None:
            remove_worktree(worktree_path, force=True)
        raise
    # On success: leave worktree for caller to merge / inspect.

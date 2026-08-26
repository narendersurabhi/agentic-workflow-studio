"""File, artifact, and workspace operation handlers.

Moved out of libs/core/tool_registry.py (Phase 5 of the harness/MCP/tool-manager/
memory layering) — CLAUDE.md's standing rule is that handler implementations
don't belong in tool_registry.py. Names are unchanged from their prior location;
only the file moved.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict

from libs.framework.tool_runtime import ToolExecutionError


def _safe_artifact_path(path: str, default_name: str) -> Path:
    base_dir = Path("/shared/artifacts")
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(path or default_name)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ToolExecutionError("Invalid path outside /shared/artifacts")
    return resolved


def _workspace_root() -> Path:
    env_root = os.getenv("WORKSPACE_DIR")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[2]


def _safe_workspace_path(path: str, default_name: str) -> Path:
    base_dir = _workspace_root()
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(path or default_name)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ToolExecutionError("Invalid path outside workspace")
    return resolved


def _write_text_file(
    payload: Dict[str, Any], default_filename: str | None = None
) -> Dict[str, Any]:
    path = payload.get("path", "")
    content = payload.get("content", "")
    if not isinstance(path, str) or not path.strip():
        if not default_filename:
            raise ToolExecutionError("Missing path")
        path = default_filename
    path = path.strip()
    if path and path.endswith("/"):
        raise ToolExecutionError("Missing file name in path")
    candidate = _safe_artifact_path(path, default_filename or "")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    return {"path": str(candidate)}


def _file_read_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    candidate = _safe_artifact_path(path, "output.txt")
    if not candidate.exists():
        raise ToolExecutionError("File not found")
    return {"content": candidate.read_text(encoding="utf-8")}


def _workspace_read_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    candidate = _safe_workspace_path(path, "output.txt")
    if not candidate.exists():
        raise ToolExecutionError("File not found")
    return {"content": candidate.read_text(encoding="utf-8")}


def _list_files(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    recursive = bool(payload.get("recursive", False))
    max_files = payload.get("max_files", 200)
    if not isinstance(max_files, int) or max_files < 1:
        max_files = 200
    root = _safe_artifact_path(path, "")
    if not root.exists():
        return {"entries": []}
    if root.is_file():
        return {"entries": [{"path": str(root), "type": "file"}]}
    entries = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for entry in iterator:
        entry_type = "dir" if entry.is_dir() else "file"
        entries.append({"path": str(entry), "type": entry_type})
        if len(entries) >= max_files:
            break
    return {"entries": entries}


def _list_workspace_files(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    recursive = bool(payload.get("recursive", False))
    max_files = payload.get("max_files", 200)
    if not isinstance(max_files, int) or max_files < 1:
        max_files = 200
    root = _safe_workspace_path(path, "")
    if not root.exists():
        return {"entries": []}
    if root.is_file():
        return {"entries": [{"path": str(root), "type": "file"}]}
    entries = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for entry in iterator:
        entry_type = "dir" if entry.is_dir() else "file"
        entries.append({"path": str(entry), "type": entry_type})
        if len(entries) >= max_files:
            break
    return {"entries": entries}


def _artifact_mkdir(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    parents = bool(payload.get("parents", True))
    exist_ok = bool(payload.get("exist_ok", True))
    candidate = _safe_artifact_path(path, "")
    candidate.mkdir(parents=parents, exist_ok=exist_ok)
    return {"path": str(candidate)}


def _workspace_mkdir(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    parents = bool(payload.get("parents", True))
    exist_ok = bool(payload.get("exist_ok", True))
    candidate = _safe_workspace_path(path, "")
    candidate.mkdir(parents=parents, exist_ok=exist_ok)
    return {"path": str(candidate)}


def _delete_path(target: Path, *, recursive: bool, missing_ok: bool) -> Dict[str, Any]:
    if not target.exists():
        if missing_ok:
            return {"path": str(target), "deleted": False}
        raise ToolExecutionError("Path not found")
    if target.is_dir():
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
    else:
        target.unlink()
    return {"path": str(target), "deleted": True}


def _artifact_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    recursive = bool(payload.get("recursive", False))
    missing_ok = bool(payload.get("missing_ok", False))
    target = _safe_artifact_path(path, "")
    return _delete_path(target, recursive=recursive, missing_ok=missing_ok)


def _workspace_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    recursive = bool(payload.get("recursive", False))
    missing_ok = bool(payload.get("missing_ok", False))
    target = _safe_workspace_path(path, "")
    return _delete_path(target, recursive=recursive, missing_ok=missing_ok)


def _replace_existing_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _rename_path(
    source: Path,
    destination: Path,
    *,
    overwrite: bool,
) -> Dict[str, Any]:
    if not source.exists():
        raise ToolExecutionError("Source path not found")
    if destination.exists():
        if not overwrite:
            raise ToolExecutionError("Destination already exists")
        _replace_existing_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    return {"path": str(destination)}


def _artifact_rename(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_artifact_path(source_path, "")
    destination = _safe_artifact_path(destination_path, "")
    return _rename_path(source, destination, overwrite=overwrite)


def _workspace_rename(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_workspace_path(source_path, "")
    destination = _safe_workspace_path(destination_path, "")
    return _rename_path(source, destination, overwrite=overwrite)


def _copy_path(
    source: Path,
    destination: Path,
    *,
    overwrite: bool,
    recursive: bool,
) -> Dict[str, Any]:
    if not source.exists():
        raise ToolExecutionError("Source path not found")
    if destination.exists():
        if not overwrite:
            raise ToolExecutionError("Destination already exists")
        _replace_existing_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if not recursive:
            raise ToolExecutionError("Source is a directory; set recursive=true")
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return {"path": str(destination)}


def _artifact_copy(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    recursive = bool(payload.get("recursive", True))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_artifact_path(source_path, "")
    destination = _safe_artifact_path(destination_path, "")
    return _copy_path(source, destination, overwrite=overwrite, recursive=recursive)


def _workspace_copy(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    recursive = bool(payload.get("recursive", True))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_workspace_path(source_path, "")
    destination = _safe_workspace_path(destination_path, "")
    return _copy_path(source, destination, overwrite=overwrite, recursive=recursive)


def _artifact_move_to_workspace(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file name in destination_path")
    source = _safe_artifact_path(source_path, "")
    if not source.exists():
        raise ToolExecutionError("Source file not found")
    destination = _safe_workspace_path(destination_path, "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise ToolExecutionError("Destination already exists")
    shutil.move(str(source), str(destination))
    return {"path": str(destination)}


def _derive_output_filename(payload: Dict[str, Any]) -> Dict[str, Any]:
    def pick_str(*values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    memory_context = _select_job_context_from_memory(payload.get("memory"))
    nested_context = memory_context.get("context_json")
    if not isinstance(nested_context, dict):
        nested_context = {}

    role_name = pick_str(
        payload.get("target_role_name"),
        payload.get("role_name"),
        payload.get("topic"),
        memory_context.get("target_role_name"),
        memory_context.get("role_name"),
        memory_context.get("topic"),
        nested_context.get("target_role_name"),
        nested_context.get("role_name"),
        nested_context.get("topic"),
    )
    job_description = pick_str(
        payload.get("job_description"),
        memory_context.get("job_description"),
        nested_context.get("job_description"),
    )
    date_value = pick_str(
        payload.get("date"),
        payload.get("today"),
        memory_context.get("date"),
        memory_context.get("today"),
        nested_context.get("date"),
        nested_context.get("today"),
    )
    output_dir = (
        pick_str(
            payload.get("output_dir"),
            memory_context.get("output_dir"),
            nested_context.get("output_dir"),
        )
        or "documents"
    )
    document_type = pick_str(
        payload.get("document_type"),
        memory_context.get("document_type"),
        nested_context.get("document_type"),
    )
    extension_hint = pick_str(
        payload.get("output_extension"),
        payload.get("file_extension"),
        payload.get("extension"),
        payload.get("format"),
        memory_context.get("output_extension"),
        memory_context.get("file_extension"),
        memory_context.get("extension"),
        memory_context.get("format"),
        nested_context.get("output_extension"),
        nested_context.get("file_extension"),
        nested_context.get("extension"),
        nested_context.get("format"),
    )
    normalized_doc_type = document_type.lower().replace("-", "_")
    known_format_types = {
        "pdf",
        "docx",
        "md",
        "markdown",
        "txt",
        "html",
        "htm",
        "json",
        "yaml",
        "yml",
        "xml",
        "csv",
    }

    def normalize_extension(raw: str) -> str:
        value = raw.strip().lower()
        if value.startswith("."):
            value = value[1:]
        if value == "markdown":
            value = "md"
        if not value:
            return ""
        if not re.fullmatch(r"[a-z0-9]{1,16}", value):
            raise ToolExecutionError("Invalid output_extension")
        return value

    output_extension = ""
    if extension_hint:
        output_extension = normalize_extension(extension_hint)
    elif normalized_doc_type in known_format_types:
        output_extension = normalize_extension(normalized_doc_type)
    if not output_extension:
        output_extension = "docx"
    if not isinstance(output_dir, str):
        output_dir = "documents"
    output_dir = output_dir.strip().strip("/")
    if not output_dir:
        output_dir = "documents"
    if output_dir.startswith("/") or ".." in Path(output_dir).parts:
        raise ToolExecutionError("Invalid output_dir")

    def clean_label(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = re.sub(r'[<>:"/\\|?*]', " ", value)
        cleaned = re.sub(r"[,_;:]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned

    def slugify(value: str, pattern: str) -> str:
        cleaned = re.sub(pattern, "_", value.lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned

    if (not isinstance(role_name, str) or not role_name.strip()) and isinstance(
        job_description, str
    ):
        role_name = _derive_role_name_from_jd(job_description)

    role_label = clean_label(role_name)
    if not role_label:
        raise ToolExecutionError("Missing target_role_name")
    if not isinstance(date_value, str) or not date_value.strip():
        date_value = datetime.now(UTC).date().isoformat()

    role_slug = slugify(role_label or str(role_name), r"[^a-z0-9]+") or "document"
    date_slug = slugify(date_value, r"[^0-9]+")
    if not date_slug:
        raise ToolExecutionError("Invalid date")
    filename = f"{role_slug}_{date_slug}.{output_extension}"
    return {
        "path": f"{output_dir}/{filename}",
        "document_type": normalized_doc_type or "document",
        "output_extension": output_extension,
    }


def _derive_role_name_from_jd(job_description: str) -> str:
    patterns = (
        r"(?im)^\s*title\s*:\s*(.+)$",
        r"(?im)^\s*role\s*:\s*(.+)$",
        r"(?im)^\s*position\s*:\s*(.+)$",
        r"(?im)\bwe are hiring (?:a|an)\s+([^.\n]+)",
        r"(?im)\bseeking (?:a|an)\s+([^.\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, job_description)
        if match:
            return match.group(1).strip(" -:,.")
    first_line = next((line.strip() for line in job_description.splitlines() if line.strip()), "")
    return first_line[:120].strip(" -:,.")


def _select_job_context_from_memory(memory: Any) -> Dict[str, Any]:
    if not isinstance(memory, dict):
        return {}
    direct = memory.get("context_json")
    if isinstance(direct, dict):
        return direct
    entries = memory.get("job_contexts")
    if not isinstance(entries, list):
        entries = memory.get("job_context")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                payload = entry.get("payload")
                if isinstance(payload, dict):
                    context_json = payload.get("context_json")
                    if isinstance(context_json, dict):
                        return context_json
                    return payload
    task_outputs = memory.get("task_outputs")
    if isinstance(task_outputs, list):
        for entry in task_outputs:
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            if isinstance(payload, dict):
                context_json = payload.get("context_json")
                if isinstance(context_json, dict):
                    return context_json
    return {}


def _search_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = payload.get("query", "")
    if not isinstance(query, str) or not query:
        raise ToolExecutionError("Missing query")
    path = payload.get("path", "")
    glob = payload.get("glob", "")
    case_sensitive = bool(payload.get("case_sensitive", False))
    use_regex = bool(payload.get("regex", False))
    context_lines = payload.get("context_lines", 0)
    if not isinstance(context_lines, int) or context_lines < 0:
        context_lines = 0
    max_matches = payload.get("max_matches", 200)
    if not isinstance(max_matches, int) or max_matches < 1:
        max_matches = 200
    root = _safe_artifact_path(path, "")
    if not root.exists():
        return {"matches": []}
    pattern = glob or "**/*"
    matches = []
    needle = query if case_sensitive else query.lower()
    regex = None
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags=flags)
        except re.error as exc:
            raise ToolExecutionError(f"Invalid regex: {exc}") from exc
    for file_path in root.glob(pattern):
        if not file_path.is_file():
            continue
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
                for idx, line in enumerate(lines, start=1):
                    hay = line if case_sensitive else line.lower()
                    matched = False
                    if regex is not None:
                        matched = regex.search(line) is not None
                    else:
                        matched = needle in hay
                    if matched:
                        start = max(0, idx - 1 - context_lines)
                        end = min(len(lines), idx - 1 + context_lines + 1)
                        context = [item.rstrip("\n") for item in lines[start:end]]
                        entry = {"path": str(file_path), "line": idx, "text": line.rstrip("\n")}
                        if context_lines:
                            entry["context"] = context
                        matches.append(entry)
                        if len(matches) >= max_matches:
                            return {"matches": matches}
        except OSError:
            continue
    return {"matches": matches}

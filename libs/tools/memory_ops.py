"""Memory tool handlers (memory.read / memory.write / memory.semantic.*).

Moved out of libs/core/tool_registry.py (Phase 5 of the harness/MCP/tool-manager/
memory layering). Names are unchanged from their prior location; only the file
moved.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from libs.framework.tool_runtime import ToolExecutionError
from libs.memory.memory_client import MemoryClient, MemoryClientError


def _memory_client() -> MemoryClient:
    base_url = os.getenv("MEMORY_API_URL", "http://api:8000").strip() or "http://api:8000"
    timeout_raw = os.getenv("MEMORY_API_TIMEOUT_S", "5.0").strip()
    try:
        timeout_s = float(timeout_raw)
    except ValueError:
        timeout_s = 5.0
    timeout_s = max(0.5, min(timeout_s, 60.0))
    return MemoryClient(base_url, timeout_s=timeout_s)


def _memory_read(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolExecutionError("Missing name")
    limit = payload.get("limit", 50)
    if not isinstance(limit, int):
        raise ToolExecutionError("limit must be an integer")
    include_expired = bool(payload.get("include_expired", False))
    try:
        entries = _memory_client().read(
            name=name.strip(),
            scope=payload.get("scope") if isinstance(payload.get("scope"), str) else None,
            key=payload.get("key") if isinstance(payload.get("key"), str) else None,
            job_id=payload.get("job_id") if isinstance(payload.get("job_id"), str) else None,
            user_id=payload.get("user_id") if isinstance(payload.get("user_id"), str) else None,
            project_id=payload.get("project_id")
            if isinstance(payload.get("project_id"), str)
            else None,
            limit=max(1, min(limit, 200)),
            include_expired=include_expired,
        )
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_read_failed:{exc}") from exc
    first = entries[0] if entries else None
    output: Dict[str, Any] = {"entries": entries, "count": len(entries)}
    if isinstance(first, dict):
        output["entry"] = first
        payload_obj = first.get("payload")
        if isinstance(payload_obj, dict):
            output["payload"] = payload_obj
    return output


def _memory_write(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolExecutionError("Missing name")
    entry_payload = payload.get("payload")
    if not isinstance(entry_payload, dict):
        raise ToolExecutionError("payload must be an object")

    request: Dict[str, Any] = {"name": name.strip(), "payload": entry_payload}
    for field in ("scope", "key", "job_id", "user_id", "project_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            request[field] = value.strip()
    ttl_seconds = payload.get("ttl_seconds")
    if ttl_seconds is not None:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ToolExecutionError("ttl_seconds must be a positive integer")
        request["ttl_seconds"] = ttl_seconds
    metadata = payload.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ToolExecutionError("metadata must be an object")
        request["metadata"] = metadata
    try:
        written = _memory_client().write(request)
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_write_failed:{exc}") from exc
    if not isinstance(written, dict):
        raise ToolExecutionError("memory_write_failed:empty_response")
    return {"entry": written}


def _memory_semantic_write(payload: Dict[str, Any]) -> Dict[str, Any]:
    fact = payload.get("fact")
    if not isinstance(fact, str) or not fact.strip():
        raise ToolExecutionError("fact is required")
    request: Dict[str, Any] = {"fact": fact.strip()}
    for field in ("subject", "namespace", "source", "source_ref", "reasoning", "key", "user_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            request[field] = value.strip()
    for list_field in ("aliases", "keywords"):
        value = payload.get(list_field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ToolExecutionError(f"{list_field} must be an array of strings")
        request[list_field] = [item.strip() for item in value if item.strip()]
    confidence = payload.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            raise ToolExecutionError("confidence must be a number between 0 and 1")
        confidence_f = float(confidence)
        if confidence_f < 0 or confidence_f > 1:
            raise ToolExecutionError("confidence must be a number between 0 and 1")
        request["confidence"] = confidence_f
    metadata = payload.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ToolExecutionError("metadata must be an object")
        request["metadata"] = metadata
    try:
        written = _memory_client().semantic_write(request)
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_semantic_write_failed:{exc}") from exc
    if not isinstance(written, dict):
        raise ToolExecutionError("memory_semantic_write_failed:empty_response")
    return written


def _memory_semantic_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolExecutionError("query is required")
    request: Dict[str, Any] = {"query": query.strip()}
    for field in ("namespace", "subject", "key", "user_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            request[field] = value.strip()
    limit = payload.get("limit")
    if limit is not None:
        if not isinstance(limit, int):
            raise ToolExecutionError("limit must be an integer")
        request["limit"] = max(1, min(limit, 50))
    min_score = payload.get("min_score")
    if min_score is not None:
        if not isinstance(min_score, (int, float)):
            raise ToolExecutionError("min_score must be a number")
        request["min_score"] = max(0.0, float(min_score))
    include_payload = payload.get("include_payload")
    if include_payload is not None:
        request["include_payload"] = bool(include_payload)
    try:
        result = _memory_client().semantic_search(request)
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_semantic_search_failed:{exc}") from exc
    if not isinstance(result, dict):
        raise ToolExecutionError("memory_semantic_search_failed:empty_response")
    return result

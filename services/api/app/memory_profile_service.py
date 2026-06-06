from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from libs.core import models

from . import memory_promotion_service, memory_store

USER_PROFILE_KEY = "profile"

# In-process cache for user profiles.  The profile changes only when memory
# promotion fires (after a turn that mentions something worth remembering).
# Caching it eliminates the SELECT on the memory table — the most expensive
# read in build_context_envelope — on every warm turn.
_PROFILE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PROFILE_CACHE_LOCK = threading.Lock()
_PROFILE_CACHE_TTL = 60.0  # seconds


def _cache_get(user_id: str) -> dict[str, Any] | None:
    with _PROFILE_CACHE_LOCK:
        entry = _PROFILE_CACHE.get(user_id)
    if entry is None:
        return None
    ts, payload = entry
    if time.monotonic() - ts > _PROFILE_CACHE_TTL:
        with _PROFILE_CACHE_LOCK:
            _PROFILE_CACHE.pop(user_id, None)
        return None
    return payload


def _cache_put(user_id: str, payload: dict[str, Any]) -> None:
    with _PROFILE_CACHE_LOCK:
        _PROFILE_CACHE[user_id] = (time.monotonic(), dict(payload))


def load_user_profile(db: Session, user_id: str) -> models.UserProfilePayload:
    cached = _cache_get(user_id)
    if cached is not None:
        return models.UserProfilePayload.model_validate(cached)
    entries = memory_store.read_memory(
        db,
        models.MemoryQuery(
            name="user_profile",
            scope=models.MemoryScope.user,
            user_id=user_id,
            key=USER_PROFILE_KEY,
            limit=1,
        ),
    )
    if not entries:
        _cache_put(user_id, {})
        return models.UserProfilePayload()
    payload = entries[0].payload or {}
    _cache_put(user_id, payload)
    return models.UserProfilePayload.model_validate(payload)


def write_user_profile(
    db: Session,
    *,
    user_id: str,
    payload: dict[str, Any],
) -> models.MemoryEntry:
    validated = models.UserProfilePayload.model_validate(payload)
    entry = memory_store.write_memory(
        db,
        models.MemoryWrite(
            name="user_profile",
            scope=models.MemoryScope.user,
            user_id=user_id,
            key=USER_PROFILE_KEY,
            payload=validated.model_dump(mode="json"),
            metadata={"promotion_source": "user_profile_service"},
        ),
    )
    _cache_put(user_id, entry.payload or {})
    return entry


def apply_user_profile_updates_from_text(
    db: Session,
    *,
    user_id: str,
    content: str,
) -> tuple[models.MemoryEntry | None, list[models.MemoryPromotionDecision]]:
    decisions = memory_promotion_service.extract_user_profile_decisions(content)
    if not decisions:
        return None, []
    existing = load_user_profile(db, user_id)
    merged_payload = memory_promotion_service.merge_user_profile_payload(
        existing.model_dump(mode="json"),
        decisions,
    )
    entry = write_user_profile(db, user_id=user_id, payload=merged_payload)
    return entry, decisions

from __future__ import annotations

import json
import logging
from typing import Any, Callable, List, Optional

from libs.core.llm_provider import (
    CacheSessionRef,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    PromptBlock,
    Stability,
)

LOGGER = logging.getLogger(__name__)

_SESSION_KEY_PREFIX = "cache_session:"
_SESSION_TTL_S = 3600  # 1 hour — exceeds Anthropic's 5-min default cache TTL


class CacheSessionStore:
    """Redis-backed store for CacheSessionRef, keyed by job_id.

    Usage:
      planner: store.save(job_id, ref)  after open_cache_session()
      worker:  store.load(job_id)       before each LLM call
      api:     store.delete(job_id)     when job reaches a terminal state
    """

    def __init__(self, redis_client: Any, ttl_s: int = _SESSION_TTL_S) -> None:
        self._redis = redis_client
        self._ttl_s = ttl_s

    def _key(self, job_id: str) -> str:
        return f"{_SESSION_KEY_PREFIX}{job_id}"

    def save(self, job_id: str, ref: CacheSessionRef) -> None:
        data = {
            "provider": ref.provider,
            "handle": ref.handle,
            "pinned_hash": ref.pinned_hash,
            "metadata": ref.metadata,
        }
        try:
            self._redis.set(self._key(job_id), json.dumps(data), ex=self._ttl_s)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "cache_session_save_failed",
                extra={"job_id": job_id, "error": str(exc)},
            )

    def load(self, job_id: str) -> CacheSessionRef | None:
        try:
            raw = self._redis.get(self._key(job_id))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "cache_session_load_failed",
                extra={"job_id": job_id, "error": str(exc)},
            )
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return CacheSessionRef(
                provider=data["provider"],
                handle=data.get("handle"),
                pinned_hash=data.get("pinned_hash"),
                metadata=data.get("metadata") or {},
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "cache_session_parse_failed",
                extra={"job_id": job_id, "error": str(exc)},
            )
            return None

    def delete(self, job_id: str) -> None:
        try:
            self._redis.delete(self._key(job_id))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "cache_session_delete_failed",
                extra={"job_id": job_id, "error": str(exc)},
            )


class CachingLLMProvider(LLMProvider):
    """Provider wrapper that transparently routes generate_request() through generate_cached().

    For each call, looks up the CacheSessionRef for the job_id in request.metadata.
    If found, converts the request into PromptBlocks and calls the inner provider's
    generate_cached(), letting the provider apply its native caching mechanism.

    Falls back to the inner provider's generate_request() when:
      - request.metadata has no job_id
      - no session is found in Redis for that job_id

    If catalog_hash_fn is provided, the current catalog hash is compared against
    the hash stored in the session. A mismatch raises LLMProviderError — catalog
    changes mid-run are not allowed because cached static blocks would be stale.
    """

    def __init__(
        self,
        inner: LLMProvider,
        session_store: CacheSessionStore,
        catalog_hash_fn: Optional[Callable[[], str]] = None,
    ) -> None:
        self._inner = inner
        self._store = session_store
        self._catalog_hash_fn = catalog_hash_fn

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        metadata = request.metadata or {}
        job_id = metadata.get("job_id") or metadata.get("session_id")
        if not job_id:
            return self._inner.generate_request(request)
        session = self._store.load(job_id)
        if session is None:
            return self._inner.generate_request(request)
        self._assert_catalog_stable(session, job_id)
        blocks = _request_to_blocks(request)
        return self._inner.generate_cached(blocks, session, request)

    def _assert_catalog_stable(self, session: CacheSessionRef, job_id: str) -> None:
        if self._catalog_hash_fn is None:
            return
        stored_hash = session.metadata.get("catalog_hash")
        if not stored_hash:
            return
        current_hash = self._catalog_hash_fn()
        if current_hash != stored_hash:
            raise LLMProviderError(
                f"capability catalog changed mid-run for job {job_id}; "
                "cached static blocks are stale — restart the job"
            )

    def generate_cached(
        self,
        blocks: List[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        return self._inner.generate_cached(blocks, session, request)

    def open_cache_session(
        self, job_id: str, static_blocks: List[PromptBlock]
    ) -> CacheSessionRef:
        return self._inner.open_cache_session(job_id, static_blocks)

    def close_cache_session(self, ref: CacheSessionRef) -> None:
        self._inner.close_cache_session(ref)


def _request_to_blocks(request: LLMRequest) -> List[PromptBlock]:
    """Convert an LLMRequest to PromptBlocks for generate_cached().

    If prompt_blocks are already set (e.g. from the planner), use them directly.
    Otherwise, map system_prompt → STATIC and user prompt → DYNAMIC.
    """
    if request.prompt_blocks:
        return list(request.prompt_blocks)
    blocks: List[PromptBlock] = []
    if request.system_prompt:
        blocks.append(PromptBlock(text=request.system_prompt, stability=Stability.STATIC))
    if request.prompt:
        blocks.append(PromptBlock(text=request.prompt, stability=Stability.DYNAMIC))
    return blocks

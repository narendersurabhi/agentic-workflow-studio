from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from libs.core.cache_session_store import (
    CacheSessionStore,
    CachingLLMProvider,
    _request_to_blocks,
)
from libs.core.llm_provider import (
    CacheSessionRef,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    PromptBlock,
    Stability,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ref(
    provider: str = "MockLLMProvider",
    pinned_hash: str | None = None,
    catalog_hash: str | None = None,
) -> CacheSessionRef:
    meta: dict[str, Any] = {}
    if catalog_hash:
        meta["catalog_hash"] = catalog_hash
    return CacheSessionRef(provider=provider, pinned_hash=pinned_hash, metadata=meta)


class _FakeRedis:
    """Minimal in-memory Redis stub."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


class _FixedProvider(LLMProvider):
    def __init__(self, response_text: str = "ok") -> None:
        self._text = response_text
        self.generate_request_calls: list[LLMRequest] = []
        self.generate_cached_calls: list[tuple] = []

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        self.generate_request_calls.append(request)
        return LLMResponse(content=self._text, input_tokens=10, output_tokens=5)

    def generate_cached(
        self,
        blocks: list[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        self.generate_cached_calls.append((blocks, session, request))
        return LLMResponse(
            content=self._text,
            input_tokens=10,
            output_tokens=5,
            cached_input_tokens=8,
        )


# ---------------------------------------------------------------------------
# CacheSessionStore
# ---------------------------------------------------------------------------

class TestCacheSessionStore:
    def test_save_and_load_roundtrip(self) -> None:
        redis = _FakeRedis()
        store = CacheSessionStore(redis)
        ref = _make_ref(catalog_hash="abc123")
        store.save("job-1", ref)

        loaded = store.load("job-1")
        assert loaded is not None
        assert loaded.provider == "MockLLMProvider"
        assert loaded.metadata["catalog_hash"] == "abc123"

    def test_load_missing_returns_none(self) -> None:
        store = CacheSessionStore(_FakeRedis())
        assert store.load("no-such-job") is None

    def test_delete_removes_entry(self) -> None:
        redis = _FakeRedis()
        store = CacheSessionStore(redis)
        store.save("job-2", _make_ref())
        store.delete("job-2")
        assert store.load("job-2") is None

    def test_save_redis_failure_is_swallowed(self) -> None:
        bad_redis = MagicMock()
        bad_redis.set.side_effect = RuntimeError("conn lost")
        store = CacheSessionStore(bad_redis)
        store.save("job-3", _make_ref())  # must not raise

    def test_load_redis_failure_returns_none(self) -> None:
        bad_redis = MagicMock()
        bad_redis.get.side_effect = RuntimeError("conn lost")
        store = CacheSessionStore(bad_redis)
        assert store.load("job-3") is None

    def test_load_corrupt_json_returns_none(self) -> None:
        redis = _FakeRedis()
        redis.set("cache_session:bad", "not-json")
        store = CacheSessionStore(redis)
        assert store.load("bad") is None

    def test_delete_redis_failure_is_swallowed(self) -> None:
        bad_redis = MagicMock()
        bad_redis.delete.side_effect = RuntimeError("conn lost")
        store = CacheSessionStore(bad_redis)
        store.delete("job-4")  # must not raise

    def test_ttl_is_passed_to_redis_set(self) -> None:
        mock_redis = MagicMock()
        store = CacheSessionStore(mock_redis, ttl_s=999)
        store.save("job-5", _make_ref())
        args, kwargs = mock_redis.set.call_args
        assert kwargs.get("ex") == 999 or (len(args) >= 3 and args[2] == 999)


# ---------------------------------------------------------------------------
# _request_to_blocks
# ---------------------------------------------------------------------------

class TestRequestToBlocks:
    def test_plain_prompt_becomes_dynamic_block(self) -> None:
        req = LLMRequest(prompt="hello world")
        blocks = _request_to_blocks(req)
        assert len(blocks) == 1
        assert blocks[0].text == "hello world"
        assert blocks[0].stability == Stability.DYNAMIC

    def test_system_prompt_becomes_static_block(self) -> None:
        req = LLMRequest(prompt="question", system_prompt="you are helpful")
        blocks = _request_to_blocks(req)
        assert len(blocks) == 2
        static = [b for b in blocks if b.stability == Stability.STATIC]
        dynamic = [b for b in blocks if b.stability == Stability.DYNAMIC]
        assert len(static) == 1
        assert static[0].text == "you are helpful"
        assert len(dynamic) == 1
        assert dynamic[0].text == "question"

    def test_prebuilt_prompt_blocks_used_directly(self) -> None:
        prebuilt = [
            PromptBlock(text="rules", stability=Stability.STATIC),
            PromptBlock(text="task", stability=Stability.DYNAMIC),
        ]
        req = LLMRequest(prompt="ignored", prompt_blocks=prebuilt)
        blocks = _request_to_blocks(req)
        assert blocks == prebuilt

    def test_empty_prompt_yields_no_blocks(self) -> None:
        req = LLMRequest(prompt="")
        blocks = _request_to_blocks(req)
        assert blocks == []


# ---------------------------------------------------------------------------
# CachingLLMProvider
# ---------------------------------------------------------------------------

class TestCachingLLMProvider:
    def _store_with_session(self, job_id: str, **ref_kwargs: Any) -> CacheSessionStore:
        redis = _FakeRedis()
        store = CacheSessionStore(redis)
        store.save(job_id, _make_ref(**ref_kwargs))
        return store

    def test_falls_back_when_no_job_id_in_metadata(self) -> None:
        inner = _FixedProvider()
        store = CacheSessionStore(_FakeRedis())
        provider = CachingLLMProvider(inner, store)

        req = LLMRequest(prompt="hi", metadata={"component": "test"})
        resp = provider.generate_request(req)

        assert resp.content == "ok"
        assert len(inner.generate_request_calls) == 1
        assert len(inner.generate_cached_calls) == 0

    def test_falls_back_when_no_session_in_redis(self) -> None:
        inner = _FixedProvider()
        store = CacheSessionStore(_FakeRedis())
        provider = CachingLLMProvider(inner, store)

        req = LLMRequest(prompt="hi", metadata={"job_id": "missing-job"})
        resp = provider.generate_request(req)

        assert resp.content == "ok"
        assert len(inner.generate_request_calls) == 1

    def test_routes_to_generate_cached_when_session_found(self) -> None:
        inner = _FixedProvider()
        store = self._store_with_session("job-10")
        provider = CachingLLMProvider(inner, store)

        req = LLMRequest(prompt="task", metadata={"job_id": "job-10"})
        resp = provider.generate_request(req)

        assert resp.cached_input_tokens == 8
        assert len(inner.generate_cached_calls) == 1
        assert len(inner.generate_request_calls) == 0

    def test_raises_on_catalog_hash_mismatch(self) -> None:
        inner = _FixedProvider()
        store = self._store_with_session("job-20", catalog_hash="hash-at-plan-time")
        provider = CachingLLMProvider(
            inner, store, catalog_hash_fn=lambda: "hash-after-catalog-changed"
        )

        req = LLMRequest(prompt="task", metadata={"job_id": "job-20"})
        with pytest.raises(LLMProviderError, match="catalog changed mid-run"):
            provider.generate_request(req)

    def test_no_error_when_catalog_hash_matches(self) -> None:
        inner = _FixedProvider()
        store = self._store_with_session("job-21", catalog_hash="stable-hash")
        provider = CachingLLMProvider(
            inner, store, catalog_hash_fn=lambda: "stable-hash"
        )

        req = LLMRequest(prompt="task", metadata={"job_id": "job-21"})
        resp = provider.generate_request(req)
        assert resp.cached_input_tokens == 8

    def test_no_check_when_session_has_no_catalog_hash(self) -> None:
        inner = _FixedProvider()
        store = self._store_with_session("job-22")  # no catalog_hash in metadata
        provider = CachingLLMProvider(
            inner, store, catalog_hash_fn=lambda: "some-hash"
        )

        req = LLMRequest(prompt="task", metadata={"job_id": "job-22"})
        resp = provider.generate_request(req)
        assert len(inner.generate_cached_calls) == 1

    def test_no_check_when_catalog_hash_fn_is_none(self) -> None:
        inner = _FixedProvider()
        store = self._store_with_session("job-23", catalog_hash="any-hash")
        provider = CachingLLMProvider(inner, store)  # no catalog_hash_fn

        req = LLMRequest(prompt="task", metadata={"job_id": "job-23"})
        resp = provider.generate_request(req)
        assert len(inner.generate_cached_calls) == 1

    def test_generate_cached_delegates_to_inner(self) -> None:
        inner = _FixedProvider()
        provider = CachingLLMProvider(inner, CacheSessionStore(_FakeRedis()))
        blocks = [PromptBlock(text="x", stability=Stability.STATIC)]
        session = _make_ref()
        req = LLMRequest(prompt="")
        resp = provider.generate_cached(blocks, session, req)
        assert len(inner.generate_cached_calls) == 1

    def test_open_and_close_cache_session_delegate_to_inner(self) -> None:
        inner = _FixedProvider()
        provider = CachingLLMProvider(inner, CacheSessionStore(_FakeRedis()))
        blocks = [PromptBlock(text="static", stability=Stability.STATIC)]
        session = provider.open_cache_session("job-99", blocks)
        assert session.provider == "_FixedProvider"
        provider.close_cache_session(session)  # must not raise

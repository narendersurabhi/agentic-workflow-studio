from __future__ import annotations

import logging
import time
from typing import Any

from .service import TextEmbedder, VectorDatabase

logger = logging.getLogger("rag.timing")


class TimingTextEmbedder:
    """Wraps any TextEmbedder and logs latency per embed_texts call.

    Emits a structured log line:
        operation="embed", latency_ms, text_count, total_chars, avg_chars_per_text
    """

    def __init__(self, inner: TextEmbedder) -> None:
        self._inner = inner

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        vectors = self._inner.embed_texts(texts)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        total_chars = sum(len(t) for t in texts)
        logger.info(
            "rag_latency",
            extra={
                "operation": "embed",
                "latency_ms": latency_ms,
                "text_count": len(texts),
                "total_chars": total_chars,
                "avg_chars_per_text": round(total_chars / len(texts), 1) if texts else 0,
            },
        )
        return vectors


class TimingVectorDatabase:
    """Wraps any VectorDatabase and logs latency per operation.

    Emits a structured log line per call:
        operation, collection, latency_ms, and operation-specific counts.
    """

    def __init__(self, inner: VectorDatabase) -> None:
        self._inner = inner

    def query(
        self,
        *,
        collection: str,
        vector: list[float],
        limit: int,
        score_threshold: float | None,
        filter_obj: dict[str, Any] | None,
        with_payload: bool,
        vector_name: str | None,
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        results = self._inner.query(
            collection=collection,
            vector=vector,
            limit=limit,
            score_threshold=score_threshold,
            filter_obj=filter_obj,
            with_payload=with_payload,
            vector_name=vector_name,
        )
        logger.info(
            "rag_latency",
            extra={
                "operation": "query",
                "collection": collection,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "result_count": len(results),
                "limit": limit,
                "filtered": filter_obj is not None,
            },
        )
        return results

    def get_collection(self, collection: str) -> dict[str, Any] | None:
        return self._inner.get_collection(collection)

    def scroll(
        self,
        *,
        collection: str,
        limit: int,
        offset: str | int | None,
        filter_obj: dict[str, Any] | None,
        with_payload: bool,
        vector_name: str | None,
    ) -> tuple[list[dict[str, Any]], str | int | None]:
        started = time.perf_counter()
        points, next_offset = self._inner.scroll(
            collection=collection,
            limit=limit,
            offset=offset,
            filter_obj=filter_obj,
            with_payload=with_payload,
            vector_name=vector_name,
        )
        logger.info(
            "rag_latency",
            extra={
                "operation": "scroll",
                "collection": collection,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "result_count": len(points),
            },
        )
        return points, next_offset

    def create_collection(
        self,
        *,
        collection: str,
        vector_size: int,
        distance: str,
        vector_name: str | None,
        on_disk_payload: bool,
    ) -> None:
        self._inner.create_collection(
            collection=collection,
            vector_size=vector_size,
            distance=distance,
            vector_name=vector_name,
            on_disk_payload=on_disk_payload,
        )

    def create_payload_index(
        self,
        *,
        collection: str,
        field_name: str,
        field_schema: str = "keyword",
    ) -> None:
        self._inner.create_payload_index(
            collection=collection,
            field_name=field_name,
            field_schema=field_schema,
        )

    def upsert_points(
        self,
        *,
        collection: str,
        points: list[dict[str, Any]],
    ) -> None:
        started = time.perf_counter()
        self._inner.upsert_points(collection=collection, points=points)
        logger.info(
            "rag_latency",
            extra={
                "operation": "upsert",
                "collection": collection,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "point_count": len(points),
            },
        )

    def delete_points(
        self,
        *,
        collection: str,
        filter_obj: dict[str, Any],
    ) -> None:
        started = time.perf_counter()
        self._inner.delete_points(collection=collection, filter_obj=filter_obj)
        logger.info(
            "rag_latency",
            extra={
                "operation": "delete",
                "collection": collection,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )

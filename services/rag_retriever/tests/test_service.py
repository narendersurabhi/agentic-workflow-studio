from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rag_retriever_core import (
    EnsureCollectionRequest,
    RetrieveRequest,
    UpsertTextEntry,
    UpsertTextsRequest,
)
from rag_retriever_core.errors import RetrieverError
from rag_retriever_core.service import (
    RetrieverService,
    RetrieverServiceConfig,
    build_qdrant_filter,
)


@dataclass
class _EmbedderStub:
    vectors: list[list[float]]

    def __post_init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [list(vector) for vector in self.vectors[: len(texts)]]


@dataclass
class _VectorDbStub:
    points: list[dict[str, Any]]
    existing_collection: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.query_calls: list[dict[str, Any]] = []
        self.created_collections: list[dict[str, Any]] = []
        self.created_payload_indexes: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []

    def query(
        self,
        *,
        collection: str,
        vector: list[float],
        limit: int,
        score_threshold: float | None,
        filter_obj: dict | None,
        with_payload: bool,
        vector_name: str | None,
    ) -> list[dict[str, Any]]:
        self.query_calls.append(
            {
                "collection": collection,
                "vector": vector,
                "limit": limit,
                "score_threshold": score_threshold,
                "filter_obj": filter_obj,
                "with_payload": with_payload,
                "vector_name": vector_name,
            }
        )
        return list(self.points)

    def get_collection(self, collection: str) -> dict[str, Any] | None:
        return self.existing_collection

    def create_collection(
        self,
        *,
        collection: str,
        vector_size: int,
        distance: str,
        vector_name: str | None,
        on_disk_payload: bool,
    ) -> None:
        self.created_collections.append(
            {
                "collection": collection,
                "vector_size": vector_size,
                "distance": distance,
                "vector_name": vector_name,
                "on_disk_payload": on_disk_payload,
            }
        )
        self.existing_collection = {
            "result": {
                "config": {
                    "params": {
                        "vectors": {
                            "size": vector_size,
                            "distance": distance,
                        }
                    }
                }
            }
        }

    def create_payload_index(
        self,
        *,
        collection: str,
        field_name: str,
        field_schema: str = "keyword",
    ) -> None:
        self.created_payload_indexes.append(
            {
                "collection": collection,
                "field_name": field_name,
                "field_schema": field_schema,
            }
        )

    def upsert_points(
        self,
        *,
        collection: str,
        points: list[dict[str, Any]],
    ) -> None:
        self.upsert_calls.append({"collection": collection, "points": points})


def _config(require_scope: bool = True) -> RetrieverServiceConfig:
    return RetrieverServiceConfig(
        qdrant_url="http://qdrant:6333",
        qdrant_api_key="",
        qdrant_collection="rag_default",
        qdrant_vector_name=None,
        qdrant_timeout_s=10.0,
        qdrant_vector_size=1536,
        qdrant_distance="Cosine",
        qdrant_on_disk_payload=True,
        qdrant_create_payload_indexes=True,
        qdrant_payload_index_fields=(
            "document_id",
            "namespace",
            "tenant_id",
            "user_id",
            "workspace_id",
            "source_uri",
        ),
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key="test-key",
        embedding_base_url="https://api.openai.com",
        embedding_timeout_s=15.0,
        top_k_default=5,
        top_k_max=20,
        require_scope=require_scope,
        payload_text_key="text",
        payload_document_id_key="document_id",
        payload_source_uri_key="source_uri",
        payload_namespace_key="namespace",
        payload_tenant_id_key="tenant_id",
        payload_user_id_key="user_id",
        payload_workspace_id_key="workspace_id",
    )


def test_build_qdrant_filter_merges_scope_and_simple_scalar_filters() -> None:
    request = RetrieveRequest(
        query="kubernetes rollout",
        tenant_id="tenant-a",
        workspace_id="ws-1",
        namespace="docs",
        filters={"repo": "agentic-workflow-studio"},
    )

    built = build_qdrant_filter(request, _config())

    assert built == {
        "must": [
            {"key": "namespace", "match": {"value": "docs"}},
            {"key": "tenant_id", "match": {"value": "tenant-a"}},
            {"key": "workspace_id", "match": {"value": "ws-1"}},
            {"key": "repo", "match": {"value": "agentic-workflow-studio"}},
        ]
    }


def test_retrieve_normalizes_matches_and_enforces_top_k() -> None:
    embedder = _EmbedderStub([[0.1, 0.2, 0.3]])
    vector_db = _VectorDbStub(
        [
            {
                "id": "chunk-1",
                "score": 0.91,
                "payload": {
                    "document_id": "doc-1",
                    "text": "Deployment uses API, planner, and worker services.",
                    "source_uri": "README.md#architecture",
                    "tenant_id": "tenant-a",
                },
            }
        ]
    )
    service = RetrieverService(config=_config(), embedder=embedder, vector_db=vector_db)

    result = service.retrieve(
        RetrieveRequest(
            query="How does deployment work?",
            tenant_id="tenant-a",
            top_k=20,
            include_text=True,
            include_metadata=True,
        )
    )

    assert embedder.calls == [["How does deployment work?"]]
    assert vector_db.query_calls[0]["limit"] == 20
    assert result.matches[0].chunk_id == "chunk-1"
    assert result.matches[0].document_id == "doc-1"
    assert result.matches[0].source_uri == "README.md#architecture"
    assert "planner" in result.matches[0].text
    assert result.matches[0].metadata["tenant_id"] == "tenant-a"


def test_retrieve_requires_scope_when_configured() -> None:
    service = RetrieverService(
        config=_config(require_scope=True),
        embedder=_EmbedderStub([[0.1, 0.2, 0.3]]),
        vector_db=_VectorDbStub([]),
    )

    try:
        service.retrieve(RetrieveRequest(query="ungrounded query"))
    except RetrieverError as exc:
        assert exc.detail == "missing_scope:one_of_tenant_id_user_id_workspace_id_required"
    else:  # pragma: no cover
        raise AssertionError("Expected RetrieverError")


def test_ensure_collection_creates_collection_and_payload_indexes() -> None:
    service = RetrieverService(
        config=_config(),
        embedder=_EmbedderStub([[0.1, 0.2, 0.3]]),
        vector_db=_VectorDbStub([]),
    )

    result = service.ensure_collection(EnsureCollectionRequest())

    assert result.collection_name == "rag_default"
    assert result.status == "created"
    assert result.vector_size == 1536
    assert len(service.vector_db.created_collections) == 1
    indexed_fields = [item["field_name"] for item in service.vector_db.created_payload_indexes]
    assert "document_id" in indexed_fields
    assert "workspace_id" in indexed_fields


def test_upsert_texts_embeds_and_upserts_points() -> None:
    embedder = _EmbedderStub([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    vector_db = _VectorDbStub([])
    service = RetrieverService(config=_config(), embedder=embedder, vector_db=vector_db)

    result = service.upsert_texts(
        UpsertTextsRequest(
            namespace="docs",
            tenant_id="tenant-a",
            workspace_id="ws-1",
            entries=[
                UpsertTextEntry(
                    document_id="readme",
                    text="Kubernetes deployment uses local overlay manifests.",
                    source_uri="README.md#kubernetes",
                    metadata={"repo": "agentic-workflow-studio"},
                ),
                UpsertTextEntry(
                    document_id="guide",
                    text="Workflow Studio supports saved drafts and versions.",
                    source_uri="docs/user-guide.md#studio",
                ),
            ],
        )
    )

    assert embedder.calls == [
        [
            "Kubernetes deployment uses local overlay manifests.",
            "Workflow Studio supports saved drafts and versions.",
        ]
    ]
    assert result.upserted_count == 2
    assert len(vector_db.upsert_calls) == 1
    upsert_points = vector_db.upsert_calls[0]["points"]
    assert upsert_points[0]["payload"]["namespace"] == "docs"
    assert upsert_points[0]["payload"]["tenant_id"] == "tenant-a"
    assert upsert_points[0]["payload"]["repo"] == "agentic-workflow-studio"
    assert upsert_points[1]["payload"]["workspace_id"] == "ws-1"
    assert len(result.chunk_ids) == 2


def test_upsert_texts_requires_scope_when_configured() -> None:
    service = RetrieverService(
        config=_config(require_scope=True),
        embedder=_EmbedderStub([[0.1, 0.2, 0.3]]),
        vector_db=_VectorDbStub([]),
    )

    try:
        service.upsert_texts(
            UpsertTextsRequest(
                entries=[
                    UpsertTextEntry(
                        document_id="doc-1",
                        text="A chunk without tenant or workspace scope.",
                    )
                ]
            )
        )
    except RetrieverError as exc:
        assert exc.detail == "missing_scope:one_of_tenant_id_user_id_workspace_id_required"
    else:  # pragma: no cover
        raise AssertionError("Expected RetrieverError")

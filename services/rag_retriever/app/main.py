from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.mcp import create_mcp_asgi_app
from libs.core import logging as core_logging
from rag_retriever_core import (
    DeleteDocumentRequest,
    DeleteDocumentResponse,
    DocumentChunksRequest,
    DocumentChunksResponse,
    DocumentListRequest,
    DocumentListResponse,
    EnsureCollectionRequest,
    EnsureCollectionResponse,
    IndexMarkdownRequest,
    IndexMarkdownResponse,
    IndexWorkspaceDirectoryRequest,
    IndexWorkspaceDirectoryResponse,
    IndexWorkspaceFileRequest,
    IndexWorkspaceFileResponse,
    RerankRequest,
    RerankResponse,
    RetrieverError,
    RetrieveRequest,
    RetrieveResponse,
    UpsertTextsRequest,
    UpsertTextsResponse,
    build_service_from_env,
)


core_logging.configure_logging("rag-retriever")
LOGGER = core_logging.get_logger("rag-retriever")
RETRIEVER_SERVICE = build_service_from_env()

MCP_APP, MCP_SESSION_MANAGER = create_mcp_asgi_app(RETRIEVER_SERVICE, LOGGER)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    try:
        ensured = RETRIEVER_SERVICE.ensure_default_collection()
        if ensured is not None:
            LOGGER.info(
                "rag_default_collection_ready",
                extra={
                    "collection_name": ensured.collection_name,
                    "status": ensured.status,
                    "vector_size": ensured.vector_size,
                },
            )
    except RetrieverError as exc:
        LOGGER.warning("rag_default_collection_not_ready", extra={"error": exc.detail})
    session_cm = MCP_SESSION_MANAGER.run()
    _app.state._mcp_session_cm = session_cm
    await session_cm.__aenter__()
    yield
    await session_cm.__aexit__(None, None, None)


app = FastAPI(title="Agentic RAG Retriever Service", lifespan=_app_lifespan)
app.state.retriever_service = RETRIEVER_SERVICE
app.state.retriever_logger = LOGGER
app.mount("/metrics", make_asgi_app())
app.mount("/mcp", MCP_APP)
app.mount("/mcp/rpc", MCP_APP)
app.mount("/mcp/rpc/mcp", MCP_APP)


@app.middleware("http")
async def _optional_bearer_auth(request: Request, call_next):
    expected = os.getenv("RAG_RETRIEVER_MCP_TOKEN", "").strip()
    if not expected:
        return await call_next(request)
    path = request.url.path
    protected = path.startswith("/mcp") or path.startswith("/retrieve")
    if not protected:
        return await call_next(request)
    actual = request.headers.get("Authorization", "").strip()
    if actual != f"Bearer {expected}":
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve_endpoint(request: RetrieveRequest) -> RetrieveResponse:
    try:
        return RETRIEVER_SERVICE.retrieve(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/retrieve/rerank", response_model=RerankResponse)
def rerank_endpoint(request: RerankRequest) -> RerankResponse:
    try:
        return RETRIEVER_SERVICE.rerank(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/documents/list", response_model=DocumentListResponse)
def list_documents_endpoint(request: DocumentListRequest) -> DocumentListResponse:
    try:
        return RETRIEVER_SERVICE.list_documents(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/documents/chunks", response_model=DocumentChunksResponse)
def document_chunks_endpoint(request: DocumentChunksRequest) -> DocumentChunksResponse:
    try:
        return RETRIEVER_SERVICE.get_document_chunks(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/documents/delete", response_model=DeleteDocumentResponse)
def delete_document_endpoint(request: DeleteDocumentRequest) -> DeleteDocumentResponse:
    try:
        return RETRIEVER_SERVICE.delete_document(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/collections")
def list_collections_endpoint() -> dict:
    try:
        return {"collections": RETRIEVER_SERVICE.list_collections()}
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/collections/ensure", response_model=EnsureCollectionResponse)
def ensure_collection_endpoint(request: EnsureCollectionRequest) -> EnsureCollectionResponse:
    try:
        return RETRIEVER_SERVICE.ensure_collection(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/index/upsert_texts", response_model=UpsertTextsResponse)
def upsert_texts_endpoint(request: UpsertTextsRequest) -> UpsertTextsResponse:
    try:
        return RETRIEVER_SERVICE.upsert_texts(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/index/workspace_file", response_model=IndexWorkspaceFileResponse)
def index_workspace_file_endpoint(request: IndexWorkspaceFileRequest) -> IndexWorkspaceFileResponse:
    try:
        return RETRIEVER_SERVICE.index_workspace_file(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/index/markdown", response_model=IndexMarkdownResponse)
def index_markdown_endpoint(request: IndexMarkdownRequest) -> IndexMarkdownResponse:
    try:
        return RETRIEVER_SERVICE.index_markdown(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/index/workspace_directory", response_model=IndexWorkspaceDirectoryResponse)
def index_workspace_directory_endpoint(
    request: IndexWorkspaceDirectoryRequest,
) -> IndexWorkspaceDirectoryResponse:
    try:
        return RETRIEVER_SERVICE.index_workspace_directory(request)
    except RetrieverError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

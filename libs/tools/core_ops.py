from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from libs.core.models import RiskLevel, ToolIntent, ToolSpec
from libs.framework.tool_runtime import Tool


PayloadHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class CoreOpsHandlers:
    file_write_text: PayloadHandler
    file_read_text: PayloadHandler
    list_files: PayloadHandler
    workspace_read_text: PayloadHandler
    workspace_list_files: PayloadHandler
    artifact_mkdir: PayloadHandler
    workspace_mkdir: PayloadHandler
    artifact_delete: PayloadHandler
    workspace_delete: PayloadHandler
    artifact_rename: PayloadHandler
    workspace_rename: PayloadHandler
    artifact_copy: PayloadHandler
    workspace_copy: PayloadHandler
    artifact_move: PayloadHandler
    derive_output_filename: PayloadHandler
    search_text: PayloadHandler
    memory_read: PayloadHandler
    memory_write: PayloadHandler
    memory_semantic_write: PayloadHandler
    memory_semantic_search: PayloadHandler
    docx_render: PayloadHandler


class FileWriteTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="File path relative to /shared/artifacts")
    content: str = Field(min_length=1, description="Text content to write")


class FilePathOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


class FileReadTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, description="File path relative to /shared/artifacts")


class FileReadTextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class ListFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = None
    recursive: bool | None = None
    max_files: int | None = Field(default=None, ge=1, le=1000)


class ListFilesEntryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    type: str


class ListFilesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[ListFilesEntryItem]


class WorkspaceReadTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, description="File path relative to workspace root")


class WorkspaceListFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = None
    recursive: bool | None = None
    max_files: int | None = Field(default=None, ge=1, le=2000)


class ArtifactMoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, description="Source path relative to /shared/artifacts")
    destination_path: str = Field(
        min_length=1, description="Destination path relative to workspace"
    )
    overwrite: bool | None = None


class ArtifactMkdirInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, description="Directory path relative to /shared/artifacts")
    parents: bool | None = None
    exist_ok: bool | None = None


class WorkspaceMkdirInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, description="Directory path relative to workspace root")
    parents: bool | None = None
    exist_ok: bool | None = None


class ArtifactDeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, description="Path relative to /shared/artifacts to delete")
    recursive: bool | None = None
    missing_ok: bool | None = None


class ArtifactDeleteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    deleted: bool


class WorkspaceDeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, description="Path relative to workspace root to delete")
    recursive: bool | None = None
    missing_ok: bool | None = None


class ArtifactRenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, description="Source path relative to /shared/artifacts")
    destination_path: str = Field(
        min_length=1, description="Destination path relative to /shared/artifacts"
    )
    overwrite: bool | None = None


class WorkspaceRenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, description="Source path relative to workspace root")
    destination_path: str = Field(
        min_length=1, description="Destination path relative to workspace root"
    )
    overwrite: bool | None = None


class ArtifactCopyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, description="Source path relative to /shared/artifacts")
    destination_path: str = Field(
        min_length=1, description="Destination path relative to /shared/artifacts"
    )
    overwrite: bool | None = None
    recursive: bool | None = None


class WorkspaceCopyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, description="Source path relative to workspace root")
    destination_path: str = Field(
        min_length=1, description="Destination path relative to workspace root"
    )
    overwrite: bool | None = None
    recursive: bool | None = None


class DeriveOutputFilenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_role_name: str | None = Field(default=None, min_length=1)
    role_name: str | None = Field(default=None, min_length=1)
    topic: str | None = Field(default=None, min_length=1)
    candidate_name: str | None = Field(default=None, min_length=1)
    first_name: str | None = Field(default=None, min_length=1)
    last_name: str | None = Field(default=None, min_length=1)
    company_name: str | None = Field(default=None, min_length=1)
    company: str | None = Field(default=None, min_length=1)
    job_description: str | None = Field(default=None, min_length=1)
    date: str | None = Field(default=None, min_length=4)
    today: str | None = Field(default=None, min_length=4)
    output_dir: str | None = None
    document_type: str | None = None
    output_extension: str | None = None
    file_extension: str | None = None
    extension: str | None = None
    format: str | None = None
    memory: dict[str, Any] | None = Field(
        default=None, description="Job context memory to derive role/date/output fields from"
    )


class DeriveOutputFilenameOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    document_type: str
    output_extension: str


class SearchTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, description="Text query to search for")
    path: str | None = None
    glob: str | None = None
    case_sensitive: bool | None = None
    regex: bool | None = None
    context_lines: int | None = Field(default=None, ge=0, le=5)
    max_matches: int | None = Field(default=None, ge=1, le=1000)


class SearchTextMatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    line: int
    text: str
    context: list[str] | None = None


class SearchTextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matches: list[SearchTextMatchItem]


class MemoryReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, description="Memory store name to read from")
    scope: str | None = None
    key: str | None = None
    job_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=200)
    include_expired: bool | None = None


class MemoryReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[dict[str, Any]]
    count: int


class MemoryWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, description="Memory store name to write to")
    payload: dict[str, Any] = Field(description="Data payload to store")
    scope: str | None = None
    key: str | None = None
    job_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    ttl_seconds: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None


class MemoryWriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry: dict[str, Any]


class MemorySemanticWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact: str = Field(min_length=1, description="Semantic fact to store")
    subject: str | None = None
    namespace: str | None = None
    aliases: list[str] | None = None
    keywords: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None
    source_ref: str | None = None
    reasoning: str | None = None
    key: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] | None = None


class MemorySemanticWriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry: dict[str, Any]
    semantic_record: dict[str, Any] | None = None


class MemorySemanticSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(
        min_length=1, description="Natural-language query for semantic memory search"
    )
    namespace: str | None = None
    subject: str | None = None
    key: str | None = None
    user_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0)
    include_payload: bool | None = None


class MemorySemanticSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matches: list[dict[str, Any]]
    count: int


def register_core_ops_tools(
    registry,
    *,
    handlers: CoreOpsHandlers,
) -> None:
    registry.register(
        Tool(
            spec=ToolSpec(
                name="file_write_text",
                description="Write text content to a file under /shared/artifacts",
                usage_guidance=(
                    "Use to write text to /shared/artifacts. Provide 'content' (required) "
                    "and 'path' (required, include the filename)."
                ),
                input_schema=FileWriteTextInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.file_write_text,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="file_read_text",
                description="Read text content from a file under /shared/artifacts",
                usage_guidance=(
                    "Use to read a text file from /shared/artifacts. Provide the 'path' "
                    "relative to /shared/artifacts."
                ),
                input_schema=FileReadTextInput.model_json_schema(),
                output_schema=FileReadTextOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.file_read_text,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="list_files",
                description="List files under /shared/artifacts",
                usage_guidance=(
                    "Use to list files under /shared/artifacts. Provide optional 'path' (relative "
                    "subdirectory), 'recursive' (bool), and 'max_files' (int)."
                ),
                input_schema=ListFilesInput.model_json_schema(),
                output_schema=ListFilesOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.low,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.list_files,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="workspace_read_text",
                description="Read text content from a file under the workspace",
                usage_guidance=(
                    "Use to read a text file from the workspace. Provide the 'path' "
                    "relative to the workspace root."
                ),
                input_schema=WorkspaceReadTextInput.model_json_schema(),
                output_schema=FileReadTextOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.workspace_read_text,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="workspace_list_files",
                description="List files under the workspace",
                usage_guidance=(
                    "Use to list files under the workspace. Provide optional 'path' (relative "
                    "subdirectory), 'recursive' (bool), and 'max_files' (int)."
                ),
                input_schema=WorkspaceListFilesInput.model_json_schema(),
                output_schema=ListFilesOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.low,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.workspace_list_files,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="artifact_move",
                description="Move a file from /shared/artifacts into the workspace",
                usage_guidance=(
                    "Use to move an artifact into the workspace. Provide 'source_path' (relative "
                    "to /shared/artifacts) and 'destination_path' (relative to the workspace). "
                    "Set 'overwrite' true to replace an existing destination."
                ),
                input_schema=ArtifactMoveInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.artifact_move,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="artifact_mkdir",
                description="Create a directory under /shared/artifacts",
                usage_guidance=(
                    "Use to create directories under /shared/artifacts. Provide 'path' (required). "
                    "Optional: 'parents' (default true), 'exist_ok' (default true)."
                ),
                input_schema=ArtifactMkdirInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.artifact_mkdir,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="workspace_mkdir",
                description="Create a directory under the workspace",
                usage_guidance=(
                    "Use to create directories under the workspace. Provide 'path' (required). "
                    "Optional: 'parents' (default true), 'exist_ok' (default true)."
                ),
                input_schema=WorkspaceMkdirInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.workspace_mkdir,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="artifact_delete",
                description="Delete a file or directory under /shared/artifacts",
                usage_guidance=(
                    "Use to delete files or directories under /shared/artifacts. Provide 'path' "
                    "(required). For non-empty directories set 'recursive' true. Optional: "
                    "'missing_ok' (default false)."
                ),
                input_schema=ArtifactDeleteInput.model_json_schema(),
                output_schema=ArtifactDeleteOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.artifact_delete,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="workspace_delete",
                description="Delete a file or directory under the workspace",
                usage_guidance=(
                    "Use to delete files or directories under the workspace. Provide 'path' "
                    "(required). For non-empty directories set 'recursive' true. Optional: "
                    "'missing_ok' (default false)."
                ),
                input_schema=WorkspaceDeleteInput.model_json_schema(),
                output_schema=ArtifactDeleteOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.workspace_delete,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="artifact_rename",
                description="Rename or move a file/directory within /shared/artifacts",
                usage_guidance=(
                    "Use to rename or move files/directories within /shared/artifacts. Provide "
                    "'source_path' and 'destination_path' (required). Optional: 'overwrite' (default false)."
                ),
                input_schema=ArtifactRenameInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.artifact_rename,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="workspace_rename",
                description="Rename or move a file/directory within the workspace",
                usage_guidance=(
                    "Use to rename or move files/directories within the workspace. Provide "
                    "'source_path' and 'destination_path' (required). Optional: 'overwrite' (default false)."
                ),
                input_schema=WorkspaceRenameInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.workspace_rename,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="artifact_copy",
                description="Copy a file/directory within /shared/artifacts",
                usage_guidance=(
                    "Use to copy files/directories within /shared/artifacts. Provide 'source_path' "
                    "and 'destination_path' (required). Optional: 'overwrite' (default false), "
                    "'recursive' (default true for directories)."
                ),
                input_schema=ArtifactCopyInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=15,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.artifact_copy,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="workspace_copy",
                description="Copy a file/directory within the workspace",
                usage_guidance=(
                    "Use to copy files/directories within the workspace. Provide 'source_path' "
                    "and 'destination_path' (required). Optional: 'overwrite' (default false), "
                    "'recursive' (default true for directories)."
                ),
                input_schema=WorkspaceCopyInput.model_json_schema(),
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=15,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.workspace_copy,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="derive_output_filename",
                description="Derive a filesystem-safe output path for generated documents",
                usage_guidance=(
                    "Use to create a safe output path for render tools. "
                    "Provide target_role_name (or role_name or topic) and date/today (YYYY-MM-DD) "
                    "to get role_date naming. If date/today is omitted, "
                    "the tool defaults to the current UTC date. "
                    "Optionally provide 'output_dir' (default: documents). "
                    "Optionally provide output_extension (or file_extension/extension/format) "
                    "to control the file extension (default: docx)."
                ),
                input_schema=DeriveOutputFilenameInput.model_json_schema(),
                output_schema=DeriveOutputFilenameOutput.model_json_schema(),
                memory_reads=["job_context", "task_outputs"],
                memory_writes=["task_outputs"],
                timeout_s=2,
                risk_level=RiskLevel.low,
                tool_intent=ToolIntent.transform,
            ),
            handler=handlers.derive_output_filename,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="search_text",
                description="Search for text in files under /shared/artifacts",
                usage_guidance=(
                    "Use to find text in files under /shared/artifacts. Provide 'query' (required), "
                    "optional 'path', 'glob', 'case_sensitive', 'regex', 'context_lines', and 'max_matches'."
                ),
                input_schema=SearchTextInput.model_json_schema(),
                output_schema=SearchTextOutput.model_json_schema(),
                timeout_s=5,
                risk_level=RiskLevel.low,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.search_text,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="memory_read",
                description="Read entries from memory store",
                usage_guidance=(
                    "Use to resolve memory pointers before downstream tool calls. "
                    "Provide 'name' and optional filters: scope, key, job_id, user_id, project_id, limit."
                ),
                input_schema=MemoryReadInput.model_json_schema(),
                output_schema=MemoryReadOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.low,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.memory_read,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="memory_write",
                description="Write an entry to memory store",
                usage_guidance=(
                    "Use to persist structured outputs for reuse across tasks and jobs. "
                    "Provide name and payload; optional scope, key, job_id, user_id, project_id, ttl_seconds, metadata."
                ),
                input_schema=MemoryWriteInput.model_json_schema(),
                output_schema=MemoryWriteOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.memory_write,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="memory_semantic_write",
                description="Write distilled semantic facts to semantic memory",
                usage_guidance=(
                    "Use to persist stable facts for later reasoning. "
                    "Provide 'fact' and optional subject/namespace/keywords/aliases/confidence. "
                    "User scope defaults to SEMANTIC_MEMORY_DEFAULT_USER_ID when user_id is omitted."
                ),
                input_schema=MemorySemanticWriteInput.model_json_schema(),
                output_schema=MemorySemanticWriteOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.memory_semantic_write,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="memory_semantic_search",
                description="Search semantic memory by natural-language query",
                usage_guidance=(
                    "Use to retrieve relevant facts for reasoning/context. "
                    "Provide 'query' and optional namespace/subject filters and score threshold."
                ),
                input_schema=MemorySemanticSearchInput.model_json_schema(),
                output_schema=MemorySemanticSearchOutput.model_json_schema(),
                timeout_s=10,
                risk_level=RiskLevel.low,
                tool_intent=ToolIntent.io,
            ),
            handler=handlers.memory_semantic_search,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="docx_render",
                description="Render a DOCX file from structured JSON and a DOCX template",
                usage_guidance=(
                    "Provide data (object), plus either template_id (resolved under /shared/templates) "
                    "or template_path. Optionally include schema_ref to validate data against a schema "
                    "from the registry before rendering. Optionally set output_path for the rendered DOCX."
                ),
                input_schema={
                    # complex validation: keep as raw dict — anyOf at top level
                    "type": "object",
                    "properties": {
                        "data": {"type": "object"},
                        "schema_ref": {"type": "string"},
                        "template_id": {"type": "string"},
                        "template_path": {"type": "string"},
                        "output_path": {"type": "string"},
                    },
                    "required": ["data", "output_path"],
                    "anyOf": [
                        {"required": ["template_id"]},
                        {"required": ["template_path"]},
                    ],
                },
                output_schema=FilePathOutput.model_json_schema(),
                timeout_s=20,
                risk_level=RiskLevel.medium,
                tool_intent=ToolIntent.render,
            ),
            handler=handlers.docx_render,
        )
    )

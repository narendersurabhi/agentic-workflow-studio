from __future__ import annotations

from typing import Any, Callable

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from libs.core.models import RiskLevel, ToolIntent, ToolSpec
from libs.framework.tool_runtime import Tool


PayloadHandler = Callable[[dict[str, Any]], dict[str, Any]]


class LlmGenerateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(description="Raw LLM completion text")


class CodingAgentGenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, description="Code generation goal")
    files: list[str] | None = None
    constraints: str | None = None
    workspace_path: str | None = None


class CodingAgentGenerateFileItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class CodingAgentGenerateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[CodingAgentGenerateFileItem]
    written_paths: list[str]


class CodingAgentAutonomousInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, description="Autonomous coding goal")
    workspace_path: str = Field(min_length=1, description="Workspace path to implement in")
    constraints: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=12)


class CodingAgentAutonomousOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_path: str
    steps_total: int
    steps_completed: int
    written_paths: list[str]


class CodingAgentPublishPrInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str = Field(min_length=1, description="GitHub repo owner")
    repo: str = Field(min_length=1, description="GitHub repo name")
    branch: str = Field(min_length=1, description="Branch to create")
    base: str = Field(min_length=1, description="Base branch for the PR")
    workspace_path: str = Field(min_length=1, description="Local workspace path to publish")
    title: str | None = None
    body: str | None = None
    message: str | None = None
    head: str | None = None
    draft: bool | None = None
    maintainer_can_modify: bool | None = None
    include_globs: list[str] | None = None
    exclude_globs: list[str] | None = None
    max_files: int | None = Field(default=None, ge=1, le=2000)
    max_file_bytes: int | None = Field(default=None, ge=1, le=5_000_000)
    max_total_bytes: int | None = Field(default=None, ge=1, le=20_000_000)


class CodingAgentPublishPrOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str
    base: str
    selected_files: int
    selected_paths_preview: list[str]
    skipped: dict[str, Any]
    branch_create: dict[str, Any]
    push_result: dict[str, Any]
    pull_request: dict[str, Any]


class AgentRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, description="Goal for the agentic loop to achieve")
    instructions: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=32)
    allowed_capability_ids: list[str] | None = None
    background: bool = Field(
        default=False,
        description="Return immediately with run_id without waiting for the loop to finish. Requires API_URL to be configured in the worker.",
    )
    workspace_isolation: Literal["none", "worktree"] = Field(
        default="none",
        description="Workspace isolation mode. 'worktree' creates a git worktree branch for the agent's file operations.",
    )
    workspace_path: str | None = Field(
        default=None,
        description="Git repository path to use for workspace isolation. Required when workspace_isolation='worktree'.",
    )
    resume_from_checkpoint_id: str | None = Field(
        default=None,
        description="If set, restore conversation state from this checkpoint and continue the loop.",
    )


class AgentRunOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str
    steps_taken: int
    tool_calls: list[dict[str, Any]]
    run_id: str | None = Field(
        default=None, description="Set when background=True: the dispatched job's run ID."
    )
    background: bool = Field(
        default=False, description="True when the agent was dispatched as a background job."
    )
    status: str | None = Field(
        default=None, description="'paused' when the agent called wait_for_input."
    )
    checkpoint_id: str | None = Field(
        default=None, description="Set when status='paused': ID to use when resuming."
    )
    question: str | None = Field(
        default=None, description="Set when status='paused': the question the agent asked."
    )


def register_llm_text_tool(
    registry,
    *,
    timeout_s: int,
    handler: PayloadHandler,
) -> None:
    registry.register(
        Tool(
            spec=ToolSpec(
                name="llm_generate",
                description="Generate text with an LLM",
                usage_guidance=(
                    "Use for open-ended text generation or reasoning. "
                    "Provide the prompt in 'text' (preferred) or 'prompt'. "
                    "Returns the raw completion in the 'text' field."
                ),
                input_schema={
                    # complex validation: keep as raw dict — anyOf at top level
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "prompt": {"type": "string", "minLength": 1},
                    },
                    "anyOf": [{"required": ["text"]}, {"required": ["prompt"]}],
                },
                output_schema=LlmGenerateOutput.model_json_schema(),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=handler,
        )
    )


def register_coding_agent_tools(
    registry,
    *,
    timeout_s: int,
    handler_generate: PayloadHandler,
    handler_autonomous: PayloadHandler,
    handler_publish_pr: PayloadHandler | None = None,
) -> None:
    registry.register(
        Tool(
            spec=ToolSpec(
                name="coding_agent_generate",
                description="Generate code files using the coding agent service",
                usage_guidance=(
                    "Use to generate code for a repo or feature. Provide 'goal' and optional "
                    "'files' (list of relative paths), 'constraints', and 'workspace_path'. "
                    "The tool calls the coding agent service and writes files to the workspace."
                ),
                input_schema=CodingAgentGenerateInput.model_json_schema(),
                output_schema=CodingAgentGenerateOutput.model_json_schema(),
                memory_writes=["task_outputs"],
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=handler_generate,
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="coding_agent_autonomous",
                description="Autonomously plan and implement a codebase in steps using the coding agent",
                usage_guidance=(
                    "Provide 'goal' and 'workspace_path'. The tool creates "
                    "IMPLEMENTATION_PLAN.md, then implements each step and updates status "
                    "in the plan file until complete."
                ),
                input_schema=CodingAgentAutonomousInput.model_json_schema(),
                output_schema=CodingAgentAutonomousOutput.model_json_schema(),
                memory_writes=["task_outputs"],
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=handler_autonomous,
        )
    )

    if handler_publish_pr is not None:
        registry.register(
            Tool(
                spec=ToolSpec(
                    name="coding_agent_publish_pr",
                    description=(
                        "Publish workspace codegen changes to GitHub via MCP (create branch, "
                        "push files, create PR)"
                    ),
                    usage_guidance=(
                        "Provide owner, repo, branch, base, and workspace_path. Optional: "
                        "title, body, message, include_globs, exclude_globs, max_files, "
                        "max_file_bytes, max_total_bytes, draft."
                    ),
                    input_schema=CodingAgentPublishPrInput.model_json_schema(),
                    output_schema=CodingAgentPublishPrOutput.model_json_schema(),
                    timeout_s=timeout_s,
                    risk_level=RiskLevel.high,
                    tool_intent=ToolIntent.io,
                ),
                handler=handler_publish_pr,
            )
        )


def register_agent_tool(
    registry,
    *,
    timeout_s: int,
    handler: PayloadHandler,
) -> None:
    registry.register(
        Tool(
            spec=ToolSpec(
                name="agent",
                description=(
                    "Run a general-purpose agentic loop. Reasons about a goal using the "
                    "configured tools and iterates until the goal is achieved or max steps "
                    "is reached."
                ),
                usage_guidance=(
                    "Provide 'goal' (required), optional 'instructions' (system prompt), "
                    "'max_steps' (default 12), and 'allowed_capability_ids' (list of "
                    "capability IDs the agent may call). Returns 'result', 'steps_taken', "
                    "and 'tool_calls'."
                ),
                input_schema=AgentRunInput.model_json_schema(),
                output_schema=AgentRunOutput.model_json_schema(),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=handler,
        )
    )

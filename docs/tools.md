# Tools

For a full engineering guide on exposing an AI agent through the capability system, see [agent-capabilities.md](agent-capabilities.md).
For the Qdrant-backed retrieval and indexing workflow, see [rag-playbook.md](rag-playbook.md).

Tools are registered in libs/tool_manager/registry.py with explicit schemas, usage guidance, and enforced timeouts.
File read/write tools only allow paths under /shared/artifacts unless using workspace_* tools.
Workspace tools operate under WORKSPACE_DIR (defaults to repo root inside the container).

Built-in tools:

- json_transform
- text_summarize
- llm_generate
- file_write_artifact
- file_write_text
- file_read_text
- list_files
- workspace_read_text
- workspace_list_files
- artifact_move
- derive_output_filename
- search_text
- sleep
- docx_render (requires output_path)
- docx_render_from_spec
- document_spec_validate
- coding_agent_publish_pr

Docx render schema pattern:
- Keep a JSON schema per template (e.g., document.json).
- Planner should generate JSON that matches the schema before calling docx_render.
- docx_render should use schema_ref/template_id that matches the template, and output_path is required.
- document_spec_validate can be used as a preflight check before rendering.

Notes on file write tools:
- file_write_artifact: quick text output; path optional (defaults to artifact.txt).
- file_write_text: write any text file; path required.

Notes on workspace tools:
- workspace_read_text: read text from the workspace; path required.
- workspace_list_files: list files and directories under the workspace.
- artifact_move: move a file from /shared/artifacts to the workspace.

Notes on derive tools:
- derive_output_filename:
  - Fallback mode: role + date naming, returns `{"path":"documents/<role>_<date>.docx"}`.
  - Writes `docx_path:latest` and `docx_path:document:latest` to memory.

Notes on coding agent:
- coding_agent_publish_pr: publishes workspace changes to GitHub via MCP (create branch, push files, open PR). Code generation itself goes through the `agent.run` capability rather than a dedicated coding-agent tool.

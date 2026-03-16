from libs.core.job_projection import compact_document_job_payload, project_job_payload_for_tool


def test_compact_document_job_payload_strips_unrelated_job_metadata() -> None:
    job = {
        "goal": "Create a DOCX from markdown",
        "status": "queued",
        "metadata": {"llm_provider": "openai"},
        "context_json": {
            "markdown_text": "# Title\n\nBody",
            "topic": "demo",
            "tone": "neutral",
            "today": "2026-03-16",
            "output_dir": "documents",
            "unrelated": {"nested": "value"},
        },
    }

    compact = compact_document_job_payload(job)

    assert compact == {
        "goal": "Create a DOCX from markdown",
        "context_json": {
            "markdown_text": "# Title\n\nBody",
            "topic": "demo",
            "tone": "neutral",
            "today": "2026-03-16",
            "output_dir": "documents",
        },
    }


def test_project_job_payload_for_tool_only_compacts_document_generation_tools() -> None:
    job = {
        "goal": "Create a DOCX from markdown",
        "status": "queued",
        "metadata": {"llm_provider": "openai"},
        "context_json": {"markdown_text": "# Title\n\nBody"},
    }

    projected = project_job_payload_for_tool("llm_generate_document_spec", job)
    untouched = project_job_payload_for_tool("github.repo.list", job)

    assert projected == {
        "goal": "Create a DOCX from markdown",
        "context_json": {"markdown_text": "# Title\n\nBody"},
    }
    assert untouched == job

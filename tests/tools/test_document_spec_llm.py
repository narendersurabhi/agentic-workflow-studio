from libs.tools.document_spec_llm import _compact_document_spec_job


def test_compact_document_spec_job_prefers_markdown_context_over_full_job() -> None:
    job = {
        "goal": "very long goal that should not be sent back to the model",
        "instruction": "stale instruction",
        "status": "queued",
        "metadata": {"llm_provider": "openai"},
        "context_json": {
            "markdown_text": "# Heading\n\nParagraph",
            "topic": "markdown to docx",
            "tone": "practical",
            "today": "2026-03-14",
            "output_dir": "documents",
        },
    }
    payload = {
        "instruction": "Transform markdown source into a DocumentSpec JSON.",
        "topic": "markdown to docx",
        "audience": "general",
        "tone": "practical",
        "today": "2026-03-14",
        "output_dir": "documents",
    }

    compact = _compact_document_spec_job(job, payload)

    assert compact == {
        "instruction": "Transform markdown source into a DocumentSpec JSON.",
        "goal": "very long goal that should not be sent back to the model",
        "topic": "markdown to docx",
        "audience": "general",
        "tone": "practical",
        "today": "2026-03-14",
        "output_dir": "documents",
        "context_json": {
            "markdown_text": "# Heading\n\nParagraph",
            "topic": "markdown to docx",
            "tone": "practical",
            "today": "2026-03-14",
            "output_dir": "documents",
        },
        "markdown_text": "# Heading\n\nParagraph",
    }


def test_compact_document_spec_job_compacts_top_level_fields_without_markdown_context() -> None:
    job = {
        "goal": "Generate a report",
        "instruction": "Generate a report",
        "topic": "Quarterly report",
        "audience": "executives",
        "status": "queued",
        "metadata": {"debug": True},
    }

    compact = _compact_document_spec_job(job, {})

    assert compact == {
        "goal": "Generate a report",
        "instruction": "Generate a report",
        "topic": "Quarterly report",
        "audience": "executives",
    }
